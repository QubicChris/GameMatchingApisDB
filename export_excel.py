"""
Export games for a kickoff date range to an Excel workbook with readable headers.

Usage:
    python export_excel.py --from 2026-05-01 --to 2026-05-07
    python export_excel.py --from 2026-05-01 --to 2026-05-31 --no-odds
    python export_excel.py --from 2026-05-01 --to 2026-05-07 --out C:/temp/may.xlsx
    python export_excel.py --from 2026-05-01 --to 2026-05-07 --preview   # row counts only
"""
import argparse
import os
import sys

import excel_export

sys.stdout.reconfigure(encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="Export games for a kickoff date range to Excel.")
    ap.add_argument("--from", dest="date_from", required=True, help="first kickoff date, YYYY-MM-DD")
    ap.add_argument("--to", dest="date_to", required=True, help="last kickoff date (inclusive), YYYY-MM-DD")
    ap.add_argument("--no-odds", action="store_true", help="leave out the odds sheets")
    ap.add_argument("--out", help="output path (default exports/<name>.xlsx)")
    ap.add_argument("--preview", action="store_true", help="print row counts only")
    args = ap.parse_args()
    include_odds = not args.no_odds

    try:
        if args.preview:
            p = excel_export.preview(args.date_from, args.date_to, include_odds)
            width = max(len(s["name"]) for s in p["sheets"])
            for s in p["sheets"]:
                flag = "  (TOO LARGE)" if s["name"] in p["too_large"] else ""
                print(f"{s['name']:<{width}}  {s['rows']:>10,}{flag}")
            return 0 if p["ok"] else 2

        out = args.out or os.path.join(
            "exports", excel_export.default_filename(args.date_from, args.date_to, include_odds))
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        counts = excel_export.build_workbook(out, args.date_from, args.date_to, include_odds)
    except (excel_export.ExportRangeError, excel_export.ExportTooLarge) as e:
        print(str(e), file=sys.stderr)
        return 2

    print(f"Wrote {out}")
    width = max(len(n) for n in counts)
    for name, n in counts.items():
        print(f"  {name:<{width}}  {n:>10,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
