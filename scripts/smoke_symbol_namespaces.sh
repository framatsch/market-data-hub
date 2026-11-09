#!/usr/bin/env bash
# Live smoke test for OpenSpec change add-symbol-namespaces (task 10.4).
#
# Queries I:SPX and F:ES (plus a stock and the legacy/alias forms) per provider and
# prints one line per call: HTTP status, error code or canonical symbol,
# source_instrument and price. Results depend on your subscriptions, so this
# reports instead of asserting. Run it against a running service with real credentials:
#
#   BASE_URL=http://localhost:8000 PROVIDERS="ibkr lseg schwab polygon" \
#     scripts/smoke_symbol_namespaces.sh | tee /tmp/opencode/symbol-smoke.txt
#
# Expected reading of a result:
#   200                      mapping and subscription work -> keep the type declared
#   501 CAPABILITY_NOT_SUPPORTED  hub has no mapping (expected: polygon/prixe futures,
#                                 schwab futures history, prixe index/future)
#   403 PROVIDER_NOT_ENTITLED     mapping reached the provider, subscription lacks it
#   400 INVALID_PROVIDER          provider not configured/enabled (credentials in keys.db)
#   other 4xx/5xx            investigate: the native notation may be wrong; remove
#                            the type from the provider's support set until verified

set -u

BASE_URL="${BASE_URL:-http://localhost:8000}"
PROVIDERS="${PROVIDERS:-ibkr lseg schwab polygon prixe}"
MARKET_DATA_TYPE="${MARKET_DATA_TYPE:-3}"
START="${START:-$(date -u -d '14 days ago' +%Y-%m-%d)}"
END="${END:-$(date -u +%Y-%m-%d)}"

command -v python3 >/dev/null || { echo "python3 is required" >&2; exit 2; }

summarize() {
  python3 - "$1" "$2" <<'PY'
import json, sys
status, path = sys.argv[1], sys.argv[2]
try:
    body = json.load(open(path))
except Exception:
    print(f"{status:>3}  (non-JSON response)")
    raise SystemExit
if "error" in body:
    err = body["error"]
    details = err.get("details") or {}
    extra = details.get("instrument") or details.get("supported") or details.get("sec_type") or ""
    print(f"{status:>3}  {err.get('code', '?')}  {extra}")
    raise SystemExit
data = body.get("data")
item = data[-1] if isinstance(data, list) and data else data
if isinstance(item, dict):
    symbol = item.get("symbol") or item.get("underlying_symbol")
    price = item.get("price", item.get("close"))
    count = f" bars={len(data)}" if isinstance(data, list) else ""
    print(f"{status:>3}  symbol={symbol} source_instrument={item.get('source_instrument')} price={price}{count}")
else:
    print(f"{status:>3}  empty data")
PY
}

call() {
  local label="$1" url="$2" out status
  out="$(mktemp)"
  status="$(curl -sS -g -o "$out" -w '%{http_code}' --max-time 60 "$url" 2>/dev/null || echo 000)"
  printf '%-9s %-42s ' "$PROVIDER" "$label"
  summarize "$status" "$out"
  rm -f "$out"
}

echo "Base URL: $BASE_URL   history: $START..$END"
echo

for PROVIDER in $PROVIDERS; do
  q="provider=$PROVIDER"
  call "last AAPL"                 "$BASE_URL/prices/AAPL/last?$q&market_data_type=$MARKET_DATA_TYPE"
  call "last I:SPX"                "$BASE_URL/prices/I:SPX/last?$q&market_data_type=$MARKET_DATA_TYPE"
  call "last ^SPX (alias, %5E)"    "$BASE_URL/prices/%5ESPX/last?$q&market_data_type=$MARKET_DATA_TYPE"
  call "last SPX?sec_type=INDEX"   "$BASE_URL/prices/SPX/last?$q&sec_type=INDEX&market_data_type=$MARKET_DATA_TYPE"
  call "last I:DJI (root table)"   "$BASE_URL/prices/I:DJI/last?$q&market_data_type=$MARKET_DATA_TYPE"
  call "last F:ES"                 "$BASE_URL/prices/F:ES/last?$q&market_data_type=$MARKET_DATA_TYPE"
  call "last ES?sec_type=future"   "$BASE_URL/prices/ES/last?$q&sec_type=future&market_data_type=$MARKET_DATA_TYPE"
  call "last F:ZN (root table)"    "$BASE_URL/prices/F:ZN/last?$q&market_data_type=$MARKET_DATA_TYPE"
  call "history I:SPX 1d"          "$BASE_URL/prices/I:SPX/history?$q&interval=1d&start=$START&end=$END"
  call "history F:ES 1d"           "$BASE_URL/prices/F:ES/history?$q&interval=1d&start=$START&end=$END"
  call "history F:ZN 1d"           "$BASE_URL/prices/F:ZN/history?$q&interval=1d&start=$START&end=$END"
  call "chain I:SPX"               "$BASE_URL/options/I:SPX/chain?$q&expiry=$(date -u -d 'next friday' +%Y-%m-%d)"
  call "negative: .SPX (422)"      "$BASE_URL/prices/.SPX/last?$q"
  call "negative: F:ES+stock (422)" "$BASE_URL/prices/F:ES/last?$q&sec_type=stock"
  echo
done

echo "Volatility (provider-independent of the price sets):"
for PROVIDER in lseg ibkr; do
  q="provider=$PROVIDER"
  call "vol I:SPX"                 "$BASE_URL/volatility/I:SPX?$q"
  call "vol F:ES"                  "$BASE_URL/volatility/F:ES?$q"
done
echo
echo "Without provider-specific subscription a 403 PROVIDER_NOT_ENTITLED is a valid outcome;"
echo "record verified combinations in openspec/changes/add-symbol-namespaces/design.md."
