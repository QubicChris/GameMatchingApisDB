"""
Export games for a kickoff date range to an Excel workbook with readable headers.

Usage:
    python export_excel.py --from 2026-05-01 --to 2026-05-07
    python export_excel.py --from 2026-05-01 --to 2026-05-31 --no-odds
    python export_excel.py --from 2026-05-01 --to 2026-05-07 --out C:/temp/may.xlsx
    python export_excel.py --from 2026-05-01 --to 2026-05-07 --preview   # row counts only
    python export_excel.py --from 2026-09-13 --to 2026-09-19 --country Spain --country Italy --market 1 --market 50 --sheets "Games,Odds"
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
    ap.add_argument("--country", action="append", default=[], help="only this country (repeatable)")
    ap.add_argument("--league", action="append", default=[], help="only this league (repeatable)")
    ap.add_argument("--market", action="append", type=int, default=[],
                    help="market id (umid), repeatable")
    ap.add_argument("--sheets", help='comma-separated sheet names to include, e.g. "Games,Odds"')
    ap.add_argument("--out", help="output path (default exports/<name>.xlsx)")
    ap.add_argument("--preview", action="store_true", help="print row counts only")
    args = ap.parse_args()
    include_odds = not args.no_odds
    sheets = tuple(n.strip() for n in args.sheets.split(",") if n.strip()) if args.sheets else ()
    filters = excel_export.ExportFilters(tuple(args.country), tuple(args.league), tuple(args.market), sheets)

    try:
        if args.preview:
            p = excel_export.preview(args.date_from, args.date_to, include_odds, filters=filters)
            width = max(len(s["name"]) for s in p["sheets"])
            for s in p["sheets"]:
                flag = "  (TOO LARGE)" if s["name"] in p["too_large"] else ""
                print(f"{s['name']:<{width}}  {s['rows']:>10,}{flag}")
            return 0 if p["ok"] else 2

        out = args.out or os.path.join(
            "exports", excel_export.default_filename(args.date_from, args.date_to, include_odds,
                                          filtered=filters.narrows_rows))
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        counts = excel_export.build_workbook(out, args.date_from, args.date_to, include_odds,
                                         filters=filters)
    except (excel_export.ExportRangeError, excel_export.ExportFilterError,
            excel_export.ExportTooLarge) as e:
        print(str(e), file=sys.stderr)
        return 2

    print(f"Wrote {out}")
    width = max(len(n) for n in counts)
    for name, n in counts.items():
        print(f"  {name:<{width}}  {n:>10,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
