<#
Read-only health check for the Pregames server (Windows). Changes nothing.

Run from the project folder on the server:
    powershell -ExecutionPolicy Bypass -File .\server_check.ps1          # quick checks
    powershell -ExecutionPolicy Bypass -File .\server_check.ps1 -Full    # also runs test_db.py (heavy)

Output goes to the screen and to server_check_report.txt.
Passwords/keys/DB URLs are masked, but glance over the report before sharing it.
#>
param([switch]$Full)

Set-Location -Path $PSScriptRoot
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"
$Report = Join-Path $PSScriptRoot "server_check_report.txt"
$Ports = 9998, 9996, 3306, 80, 443
$LogPattern = 'INGEST\] Done|\[FAILED\]|Parse failed|500 error'

function Mask([string]$s) {
    $s = $s -replace '(mysql[^:]*://[^:]+:)[^@]+@', '$1****@'
    $s -replace '(?i)((KEY|TOKEN|SECRET|PASSWORD)[A-Za-z_]*=)\S+', '$1****'
}

function Section($title) { ""; "===== $title =====" }

function Summarize-Log($path) {
    "-- $path"
    $hits = @(Select-String -Path $path -Pattern $LogPattern -ErrorAction SilentlyContinue | ForEach-Object { $_.Line })
    $runsWithFailures = @($hits | Where-Object { $_ -match 'INGEST\] Done.*failed=[1-9]' })
    $failedGames = @($hits | Where-Object { $_ -match '\[FAILED\]' })
    "   ingest runs:        $(@($hits | Where-Object { $_ -match 'INGEST\] Done' }).Count)"
    "   runs with failures: $($runsWithFailures.Count)"
    "   failed-game lines:  $($failedGames.Count)"
    "   parse failures:     $(@($hits | Where-Object { $_ -match 'Parse failed' }).Count)"
    "   500 errors:         $(@($hits | Where-Object { $_ -match '500 error' }).Count)"
    "   -- latest runs with failures:"
    $runsWithFailures | Select-Object -Last 5
    "   -- latest failed games:"
    $failedGames | Select-Object -Last 5 | ForEach-Object { if ($_.Length -gt 300) { $_.Substring(0, 300) } else { $_ } }
}

$Py = $null
foreach ($p in ".venv\Scripts\python.exe", "venv\Scripts\python.exe", "env\Scripts\python.exe") {
    if (Test-Path $p) { $Py = (Resolve-Path $p).Path; break }
}
if (-not $Py) { $Py = (Get-Command python -ErrorAction SilentlyContinue).Source }

$DbChecks = @'
import collections
import datetime
import json
import os
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path.cwd() / ".env")
except ImportError:
    pass
from sqlalchemy import create_engine, text

url = os.getenv("DATABASE_URL")
if not url:
    sys.exit("DATABASE_URL not found in environment or .env")

# Belt and braces: every transaction on this connection is read-only.
engine = create_engine(url, connect_args={"init_command": "SET SESSION TRANSACTION READ ONLY"})
conn = engine.connect()


def q(sql, **p):
    return conn.execute(text(sql), p).fetchall()


def one(sql, **p):
    return conn.execute(text(sql), p).scalar()


def table_exists(name):
    return bool(one("SELECT COUNT(*) FROM information_schema.tables "
                    "WHERE table_schema = DATABASE() AND table_name = :t", t=name))


def check_table_sizes():
    for name, rows, mb in q("""
        SELECT table_name, table_rows, ROUND((data_length + index_length) / 1024 / 1024)
        FROM information_schema.tables WHERE table_schema = DATABASE()
        ORDER BY (data_length + index_length) DESC"""):
        print(f"  {name:<20} ~{int(rows or 0):>13,} rows  {int(mb or 0):>8,} MB")


def check_coverage():
    total, matched = q("SELECT COUNT(*), COALESCE(SUM(sofa_event_id IS NOT NULL), 0) FROM games")[0]
    print(f"  games: {total:,}   matched to Sofasport: {int(matched):,}")
    for t in ("sofa_odds", "sofa_statistics", "sofa_incidents"):
        if not table_exists(t):
            print(f"  {t:<16} TABLE MISSING")
            continue
        rows, games = q(f"SELECT COUNT(*), COUNT(DISTINCT game_id) FROM {t}")[0]
        print(f"  {t:<16} {rows:>10,} rows covering {games:>7,} games "
              f"({games / matched * 100 if matched else 0:.0f}% of matched games)")


def check_api_quota():
    if not table_exists("api_call_log"):
        print("  api_call_log TABLE MISSING - the monthly quota guard in batch_match_sofa.py is not working")
        return
    now = datetime.datetime.utcnow()
    if now.day >= 18:
        cycle = now.replace(day=18, hour=0, minute=0, second=0, microsecond=0)
    else:
        y, m = (now.year, now.month - 1) if now.month > 1 else (now.year - 1, 12)
        cycle = now.replace(year=y, month=m, day=18, hour=0, minute=0, second=0, microsecond=0)
    used = one("SELECT COUNT(*) FROM api_call_log WHERE provider = 'rapidapi' AND called_at >= :c", c=cycle)
    print(f"  RapidAPI calls since {cycle.date()}: {used:,} / 9,990")
    print("  calls per day, last 14 days:")
    for d, n in q("SELECT DATE(called_at), COUNT(*) FROM api_call_log "
                  "WHERE called_at >= NOW() - INTERVAL 14 DAY GROUP BY 1 ORDER BY 1"):
        print(f"    {d}  {n:>5}")


def check_duplicates():
    exact = one("""SELECT COUNT(*) FROM (SELECT 1 FROM games
                   GROUP BY home_team, away_team, date_time_starts_utc, league HAVING COUNT(*) > 1) x""")
    print(f"  exact duplicate games (same teams, kickoff, league): {exact:,}")
    same_day = q("""SELECT home_team, away_team, DATE(date_time_starts_utc) d, COUNT(*) n,
                           GROUP_CONCAT(DISTINCT TIME(date_time_starts_utc)) times,
                           GROUP_CONCAT(id) ids
                    FROM games GROUP BY home_team, away_team, DATE(date_time_starts_utc)
                    HAVING COUNT(*) > 1 ORDER BY d DESC""")
    print(f"  same fixture stored more than once on one day (kickoff/league changed): {len(same_day):,}")
    for r in same_day[:5]:
        print(f"    {r.d} {r.home_team} vs {r.away_team}  times={r.times}  ids={r.ids}")
    shared = q("""SELECT sofa_event_id, GROUP_CONCAT(id) ids FROM games
                  WHERE sofa_event_id IS NOT NULL GROUP BY sofa_event_id HAVING COUNT(*) > 1""")
    print(f"  Sofasport events assigned to more than one game: {len(shared):,}")
    for r in shared[:5]:
        print(f"    sofa_event_id={r.sofa_event_id}  game ids={r.ids}")


def check_daily_volume():
    print("  kickoff date  games  matched  w/odds  w/incidents")
    for d, g, m, o, i in q("""
        SELECT DATE(g.date_time_starts_utc), COUNT(*), SUM(g.sofa_event_id IS NOT NULL),
               SUM(o.game_id IS NOT NULL), SUM(i.game_id IS NOT NULL)
        FROM games g
        LEFT JOIN (SELECT DISTINCT game_id FROM sofa_odds) o ON o.game_id = g.id
        LEFT JOIN (SELECT DISTINCT game_id FROM sofa_incidents) i ON i.game_id = g.id
        WHERE g.date_time_starts_utc >= UTC_TIMESTAMP() - INTERVAL 30 DAY
          AND g.date_time_starts_utc <  UTC_TIMESTAMP() + INTERVAL 2 DAY
        GROUP BY 1 ORDER BY 1"""):
        print(f"  {d}  {g:>6} {int(m):>8} {int(o):>7} {int(i):>12}")


def check_incident_loss():
    """Compare saved incident JSON with what made it into sofa_incidents."""
    files = sorted(Path("sofa_calls").glob("*/incidents/*.json"))
    print(f"  saved incident JSON files: {len(files):,}")
    if not files:
        return
    latest = {}
    for f in files:
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"    unreadable {f}: {e}")
            continue
        sid = d.get("sofa_event_id")
        if sid is not None and (sid not in latest or str(d.get("fetched_at")) >= str(latest[sid].get("fetched_at"))):
            latest[sid] = d
    db_counts = {sid: n for sid, n in q("SELECT sofa_event_id, COUNT(*) FROM sofa_incidents GROUP BY sofa_event_id")}

    compared = never_loaded = expected = in_db = 0
    collisions = collections.Counter()
    events_hit = set()
    goal_events_hit = set()
    for sid, d in latest.items():
        items = d.get("data") or []
        keys = collections.Counter(
            (i.get("incidentType"), i.get("time"), i.get("reversedPeriodTime"))
            for i in items
            if None not in (i.get("incidentType"), i.get("time"), i.get("reversedPeriodTime"))
        )
        for (itype, _, _), n in keys.items():
            if n > 1:
                collisions[itype] += n - 1
                events_hit.add(sid)
                if itype == "goal":
                    goal_events_hit.add(sid)
        if db_counts.get(sid, 0) == 0:
            never_loaded += 1
            continue
        compared += 1
        expected += len(items)
        in_db += db_counts[sid]

    print(f"  events compared: {compared:,}  (another {never_loaded:,} have JSON but no DB rows)")
    print(f"  incidents in JSON: {expected:,}   in DB: {in_db:,}   missing: {expected - in_db:,}")
    print(f"  predicted same-minute overwrites by type: {dict(collisions) or 'none'}")
    print(f"  events affected: {len(events_hit):,}   of which with a lost goal (skews Blown Leads): {len(goal_events_hit):,}")


for title, fn in [
    ("Table sizes (approximate)", check_table_sizes),
    ("Sofasport coverage", check_coverage),
    ("RapidAPI quota", check_api_quota),
    ("Duplicates", check_duplicates),
    ("Last 30 days by kickoff date", check_daily_volume),
    ("Incident overwrite check", check_incident_loss),
]:
    print(f"\n--- {title}")
    try:
        fn()
    except Exception as e:
        print(f"  ERROR: {type(e).__name__}: {str(e).splitlines()[0]}")
        conn.rollback()

conn.close()
'@

& {
    Section "Host"
    "$env:COMPUTERNAME  $((Get-CimInstance Win32_OperatingSystem).Caption)"
    "now (UTC): $((Get-Date).ToUniversalTime().ToString('yyyy-MM-dd HH:mm:ss'))"
    "last boot: $((Get-CimInstance Win32_OperatingSystem).LastBootUpTime)"
    "project:   $PSScriptRoot"
    if ($Py) { "python:    $Py ($(& $Py --version 2>&1))" } else { "python:    NOT FOUND" }

    Section "Code version"
    if (Get-Command git -ErrorAction SilentlyContinue) {
        git log -1 --oneline 2>&1 | ForEach-Object { "$_" }
        "-- local changes vs git:"
        git status --short 2>&1 | Select-Object -First 30 | ForEach-Object { "$_" }
    } else {
        "git not installed - newest .py files instead:"
        Get-ChildItem *.py | Sort-Object LastWriteTime -Descending | Select-Object -First 10 |
            ForEach-Object { "  {0:yyyy-MM-dd HH:mm}  {1}" -f $_.LastWriteTime, $_.Name }
    }

    Section ".env settings (names only, plus SAVE_* flags)"
    if (Test-Path .env) {
        (Get-Content .env | Where-Object { $_ -match '^[A-Za-z_]+=' } | ForEach-Object { ($_ -split '=')[0] }) -join ' '
        Get-Content .env | Where-Object { $_ -match '^SAVE_' }
    } else { ".env not found" }

    Section "Disk"
    $drive = (Get-Item $PSScriptRoot).PSDrive
    "drive {0}: {1:N1} GB free of {2:N1} GB" -f $drive.Name, ($drive.Free / 1GB), (($drive.Used + $drive.Free) / 1GB)
    foreach ($dir in @(Get-ChildItem -Directory -Filter "payloads*") + @(Get-Item sofa_calls, reports -ErrorAction SilentlyContinue)) {
        $m = Get-ChildItem $dir.FullName -Recurse -File -ErrorAction SilentlyContinue | Measure-Object Length -Sum
        "  {0,-20} {1,8:N0} files  {2,10:N1} MB" -f $dir.Name, $m.Count, ($m.Sum / 1MB)
    }
    $failed = @(Get-ChildItem payloads -Filter "*_FAILED.json" -ErrorAction SilentlyContinue)
    "FAILED payload files in payloads\: $($failed.Count)"
    $failed | Sort-Object LastWriteTime -Descending | Select-Object -First 5 |
        ForEach-Object { "  {0:yyyy-MM-dd HH:mm}  {1,10:N1} MB  {2}" -f $_.LastWriteTime, ($_.Length / 1MB), $_.Name }

    Section "Running processes"
    Get-CimInstance Win32_Process |
        Where-Object { $_.CommandLine -match 'uvicorn|streamlit|batch_match|load_sofa|main:app' } |
        ForEach-Object { "  pid={0} started={1:yyyy-MM-dd HH:mm}  {2}" -f $_.ProcessId, $_.CreationDate, $_.CommandLine }

    Section "Listening ports"
    Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object { $Ports -contains $_.LocalPort } |
        Sort-Object LocalPort -Unique | ForEach-Object {
            "  {0}:{1}  {2}" -f $_.LocalAddress, $_.LocalPort, (Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue).ProcessName
        }

    Section "Firewall"
    Get-NetFirewallProfile -ErrorAction SilentlyContinue | ForEach-Object { "  profile {0}: enabled={1}" -f $_.Name, $_.Enabled }
    "-- enabled inbound allow rules for $($Ports -join ', '):"
    Get-NetFirewallRule -Direction Inbound -Enabled True -Action Allow -ErrorAction SilentlyContinue | ForEach-Object {
        $rule = $_
        $ruleports = @(($rule | Get-NetFirewallPortFilter).LocalPort)
        if ($ruleports | Where-Object { $Ports -contains $_ }) {
            $addr = ($rule | Get-NetFirewallAddressFilter).RemoteAddress -join ','
            "  {0}  ports={1}  from={2}" -f $rule.DisplayName, ($ruleports -join ','), $addr
        }
    }

    Section "Scheduled tasks running Python / project scripts"
    Get-ScheduledTask -ErrorAction SilentlyContinue | Where-Object {
        ($_.Actions | ForEach-Object { "$($_.Execute) $($_.Arguments) $($_.WorkingDirectory)" }) -match 'python|batch_match|load_sofa|send_payload|uvicorn|streamlit|pregame|GameMatching'
    } | ForEach-Object {
        $info = $_ | Get-ScheduledTaskInfo
        "  {0}{1}  state={2}  last run={3}  result={4}  next={5}" -f $_.TaskPath, $_.TaskName, $_.State, $info.LastRunTime, $info.LastTaskResult, $info.NextRunTime
        $_.Actions | ForEach-Object { "      runs: $($_.Execute) $($_.Arguments)" }
        $_.Triggers | ForEach-Object { "      trigger: $($_.CimClass.CimClassName -replace 'MSFT_Task','') start=$($_.StartBoundary) every=$($_.Repetition.Interval)" }
    }

    Section "Windows services running Python / the API"
    $LogFiles = @()
    Get-CimInstance Win32_Service | Where-Object { $_.PathName -match 'python|uvicorn|streamlit|nssm|pregame|GameMatching' } | ForEach-Object {
        "  {0}  state={1}  start={2}  {3}" -f $_.Name, $_.State, $_.StartMode, $_.PathName
        $params = "HKLM:\SYSTEM\CurrentControlSet\Services\$($_.Name)\Parameters"
        if (Test-Path $params) {
            $p = Get-ItemProperty $params
            if ($p.AppParameters) { "      app args: $($p.AppParameters)" }
            if ($p.AppDirectory)  { "      app dir:  $($p.AppDirectory)" }
            foreach ($log in @($p.AppStdout, $p.AppStderr) | Where-Object { $_ } | Sort-Object -Unique) {
                if (-not [IO.Path]::IsPathRooted($log) -and $p.AppDirectory) { $log = Join-Path $p.AppDirectory $log }
                "      log: $log"
                $LogFiles += $log
            }
        }
    }

    Section "Ingest results in logs"
    $LogFiles += Get-ChildItem -Path $PSScriptRoot -Recurse -Depth 2 -Include *.log, *.out -File -ErrorAction SilentlyContinue |
        ForEach-Object { $_.FullName }
    $LogFiles = $LogFiles | Where-Object { $_ -and (Test-Path $_) } | Sort-Object -Unique
    if ($LogFiles) {
        foreach ($f in $LogFiles) { Summarize-Log $f }
    } else {
        "Could not find any API log files. If the API runs in an open console window, its log only exists there -"
        "say how it is started (service, scheduled task, .bat file, console window)."
    }

    Section "Database checks"
    if ($Py) {
        $tmp = Join-Path $env:TEMP "pregames_server_check.py"
        Set-Content -Path $tmp -Value $DbChecks -Encoding UTF8
        & $Py -u $tmp 2>&1 | ForEach-Object { "$_" }
        Remove-Item $tmp -ErrorAction SilentlyContinue
    } else { "skipped - python not found" }

    if ($Full) {
        Section "test_db.py"
        & $Py -u test_db.py 2>&1 | ForEach-Object { "$_" }
    } else {
        ""
        "(skipped test_db.py - run with -Full to include it; it scans the big selections table)"
    }
} | ForEach-Object { Mask "$_" } | Tee-Object -Variable lines

$lines | Out-File -FilePath $Report -Encoding utf8
""
"Report saved to $Report"
