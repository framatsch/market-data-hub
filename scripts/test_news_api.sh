#!/bin/bash

# Market Data Hub - Company News API Test Suite
# Tests alle Endpoints der News API mit Mock Provider

set -e

BASE_URL="http://localhost:8000"
PROVIDER="mock"

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Test counter
PASSED=0
FAILED=0

# Helper function to print test header
print_test() {
    echo -e "\n${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BLUE}📋 TEST: $1${NC}"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
}

# Helper function to check response status
check_response() {
    local response=$1
    local test_name=$2
    local expected_status=$3

    if echo "$response" | grep -q '"error"'; then
        if [ "$expected_status" == "error" ]; then
            echo -e "${GREEN}✅ PASSED${NC}: $test_name (error as expected)"
            ((PASSED++))
            return 0
        else
            echo -e "${RED}❌ FAILED${NC}: $test_name"
            echo "Response: $response"
            ((FAILED++))
            return 1
        fi
    else
        if [ "$expected_status" == "success" ]; then
            echo -e "${GREEN}✅ PASSED${NC}: $test_name"
            ((PASSED++))
            return 0
        else
            echo -e "${RED}❌ FAILED${NC}: $test_name (expected error)"
            echo "Response: $response"
            ((FAILED++))
            return 1
        fi
    fi
}

# Check if API is running
check_api_running() {
    if ! curl -s "$BASE_URL/health" > /dev/null 2>&1; then
        echo -e "${RED}❌ ERROR: API is not running${NC}"
        echo "Start the API with: uvicorn app.main:app --reload"
        exit 1
    fi
}

# Test 1: Basic News Request
test_basic_news() {
    print_test "Basic News Request (AAPL, default 30 days)"

    response=$(curl -s "${BASE_URL}/companies/AAPL/news?provider=${PROVIDER}" | jq '.')
    check_response "$response" "Basic news request" "success"

    # Check response structure
    if echo "$response" | jq -e '.data | length > 0' > /dev/null 2>&1; then
        echo -e "${GREEN}✓${NC} Found $(echo "$response" | jq '.meta.total') articles"
    fi
}

# Test 2: Days Filter
test_days_filter() {
    print_test "Days Filter (Last 7 days)"

    response=$(curl -s "${BASE_URL}/companies/AAPL/news?provider=${PROVIDER}&days=7" | jq '.')
    check_response "$response" "Days filter" "success"
}

# Test 3: Category Filter
test_category_filter() {
    print_test "Category Filter (earnings only)"

    response=$(curl -s "${BASE_URL}/companies/AAPL/news?provider=${PROVIDER}&category=earnings" | jq '.')
    check_response "$response" "Category filter" "success"

    if echo "$response" | jq -e '.data[0].category == "earnings"' > /dev/null 2>&1; then
        echo -e "${GREEN}✓${NC} Category filter working correctly"
    fi
}

# Test 4: Pagination
test_pagination() {
    print_test "Pagination (limit=2, offset=0)"

    response=$(curl -s "${BASE_URL}/companies/AAPL/news?provider=${PROVIDER}&limit=2&offset=0" | jq '.')
    check_response "$response" "Pagination" "success"

    limit=$(echo "$response" | jq '.meta.limit')
    if [ "$limit" == "2" ]; then
        echo -e "${GREEN}✓${NC} Pagination limit correctly set to $limit"
    fi
}

# Test 5: CSV Export
test_csv_export() {
    print_test "CSV Export"

    response=$(curl -s "${BASE_URL}/companies/AAPL/news?provider=${PROVIDER}&format=csv")

    if echo "$response" | grep -q "article_id"; then
        echo -e "${GREEN}✅ PASSED${NC}: CSV export"
        echo -e "${GREEN}✓${NC} CSV header found"
        ((PASSED++))
    else
        echo -e "${RED}❌ FAILED${NC}: CSV export"
        ((FAILED++))
    fi
}

# Test 6: Multiple Symbols
test_multiple_symbols() {
    print_test "Multiple Symbols (AAPL, MSFT, GOOGL)"

    for symbol in AAPL MSFT GOOGL; do
        response=$(curl -s "${BASE_URL}/companies/${symbol}/news?provider=${PROVIDER}" | jq '.')
        check_response "$response" "News for $symbol" "success" || continue
    done
}

# Test 7: Invalid Symbol
test_invalid_symbol() {
    print_test "Invalid Symbol (INVALID)"

    response=$(curl -s "${BASE_URL}/companies/INVALID/news?provider=${PROVIDER}" | jq '.')
    check_response "$response" "Invalid symbol error" "error"
}

# Test 8: Provider List
test_provider_list() {
    print_test "Provider List"

    response=$(curl -s "${BASE_URL}/providers" | jq '.')

    if echo "$response" | grep -q '"mock"'; then
        echo -e "${GREEN}✅ PASSED${NC}: Provider list includes mock"
        echo -e "${GREEN}✓${NC} Mock provider registered"
        ((PASSED++))
    else
        echo -e "${RED}❌ FAILED${NC}: Mock provider not in list"
        ((FAILED++))
    fi
}

# Test 9: Limit Parameter
test_limit_parameter() {
    print_test "Limit Parameter (limit=1)"

    response=$(curl -s "${BASE_URL}/companies/AAPL/news?provider=${PROVIDER}&limit=1" | jq '.')
    check_response "$response" "Limit parameter" "success"

    data_length=$(echo "$response" | jq '.data | length')
    if [ "$data_length" == "1" ]; then
        echo -e "${GREEN}✓${NC} Limit correctly returned 1 article"
    fi
}

# Test 10: Offset Parameter
test_offset_parameter() {
    print_test "Offset Parameter (offset=1)"

    response=$(curl -s "${BASE_URL}/companies/AAPL/news?provider=${PROVIDER}&offset=1" | jq '.')
    check_response "$response" "Offset parameter" "success"

    offset=$(echo "$response" | jq '.meta.offset')
    if [ "$offset" == "1" ]; then
        echo -e "${GREEN}✓${NC} Offset correctly set to 1"
    fi
}

# Main execution
main() {
    echo -e "${YELLOW}╔════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${YELLOW}║  Market Data Hub - Company News API Test Suite${NC}            ${YELLOW}║${NC}"
    echo -e "${YELLOW}║  Provider: ${PROVIDER}${NC}                                          ${YELLOW}║${NC}"
    echo -e "${YELLOW}╚════════════════════════════════════════════════════════════╝${NC}"

    # Check if API is running
    echo -e "\n${YELLOW}Checking API health...${NC}"
    check_api_running
    echo -e "${GREEN}✅ API is running${NC}\n"

    # Run tests
    test_basic_news
    test_days_filter
    test_category_filter
    test_pagination
    test_csv_export
    test_multiple_symbols
    test_invalid_symbol
    test_provider_list
    test_limit_parameter
    test_offset_parameter

    # Summary
    echo -e "\n${YELLOW}╔════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${YELLOW}║                      TEST SUMMARY${NC}                         ${YELLOW}║${NC}"
    echo -e "${YELLOW}╚════════════════════════════════════════════════════════════╝${NC}"

    total=$((PASSED + FAILED))
    percentage=$((PASSED * 100 / total))

    echo -e "\n✅ Passed: ${GREEN}$PASSED${NC}"
    echo -e "❌ Failed: ${RED}$FAILED${NC}"
    echo -e "📊 Total:  $total"
    echo -e "📈 Rate:   ${GREEN}${percentage}%${NC}\n"

    if [ $FAILED -eq 0 ]; then
        echo -e "${GREEN}✨ All tests passed! API is working correctly.${NC}\n"
        exit 0
    else
        echo -e "${RED}Some tests failed. Please check the output above.${NC}\n"
        exit 1
    fi
}

# Run main function
main "$@"
