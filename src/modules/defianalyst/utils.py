import math
from typing import Dict, List, Any, Tuple
from datetime import datetime


def format_price(price: float) -> str:
    """
    Format a USD price with appropriate precision.

    - >= $1: 2 decimal places (e.g. "$1,234.56")
    - < $1:  2 significant digits after the first non-zero decimal digit
             (e.g. $0.004512 -> "$0.00451", $0.09123 -> "$0.0912")
    """
    if price >= 1:
        return f"${price:,.2f}"
    if price <= 0:
        return "$0.00"
    # Count leading zeros after the decimal point
    # e.g. 0.004512 -> -log10(0.004512) = 2.34 -> floor = 2 leading zeros
    leading_zeros = -math.floor(math.log10(price)) - 1
    decimals = leading_zeros + 3
    return f"${price:.{decimals}f}"


async def is_asset_reference(message: str, asset_name: str) -> bool:
    """
    Use a lightweight LLM check to determine whether a short word in a
    message actually refers to the crypto asset or is just a common word.

    Only intended for name matches with 5 or fewer characters where
    ambiguity with everyday English is likely.

    Returns True if the word refers to the asset, False otherwise.
    """
    from pydantic_ai import Agent

    agent = Agent(
        "mistral:mistral-small-latest",
        output_type=bool,
        system_prompt=(
            "You determine whether a word in a user's message refers to "
            "a cryptocurrency/token or is just a common English word. "
            "Respond with true ONLY if the user is clearly talking about "
            "the crypto asset. Respond with false if the word is used as "
            "a normal English word."
        ),
    )

    prompt = (
        f'In the following message, does the word "{asset_name}" refer to '
        f'the cryptocurrency token called "{asset_name}", or is it used as '
        f'a regular English word?\n\nMessage: "{message}"'
    )

    result = await agent.run(prompt)
    return result.output


def filter_by_min_volume(coins: List[Dict], min_volume: float = 50000) -> List[Dict]:
    """
    Filter coins by minimum 24h trading volume.

    Args:
        coins: List of coin dictionaries with 'total_volume' field
        min_volume: Minimum 24h volume threshold (default: $50,000)

    Returns:
        Filtered list of coins meeting volume requirement
    """
    return [c for c in coins if c.get("total_volume", 0) >= min_volume]


def calculate_price_change(start_price: float, end_price: float) -> Tuple[float, float]:
    """
    Calculate absolute and percentage price change.

    Args:
        start_price: Starting price
        end_price: Ending price

    Returns:
        Tuple of (absolute_change, percentage_change)
    """
    absolute_change = end_price - start_price
    percentage_change = ((end_price - start_price) / start_price) * 100 if start_price > 0 else 0
    return absolute_change, percentage_change


def extract_price_range_from_chart(chart_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract start/end prices and dates from market_chart response.

    Args:
        chart_data: Response from get_coin_market_chart with 'prices' array

    Returns:
        Dict with start_price, end_price, start_date, end_date

    Raises:
        ValueError: If insufficient price data available
    """
    prices = chart_data.get("prices", [])
    if not prices or len(prices) < 2:
        raise ValueError("Insufficient price data")

    start_timestamp, start_price = prices[0]
    end_timestamp, end_price = prices[-1]

    return {
        "start_price": start_price,
        "end_price": end_price,
        "start_date": datetime.fromtimestamp(start_timestamp / 1000).strftime("%Y-%m-%d"),
        "end_date": datetime.fromtimestamp(end_timestamp / 1000).strftime("%Y-%m-%d")
    }


def format_performance_summary(coins: List[Dict], metric: str, top_n: int = 5) -> str:
    """
    Format top performers into technical summary text.

    Args:
        coins: List of coin dicts with performance data
        metric: The metric used for ranking (e.g., "price_change_percentage_7d")
        top_n: Number of results to include

    Returns:
        Formatted string with coin rankings
    """
    if not coins:
        return "No data available"

    timeframe_map = {
        "price_change_percentage_1h_in_currency": "1 hour",
        "price_change_percentage_24h": "24 hours",
        "price_change_percentage_7d_in_currency": "7 days",
        "price_change_percentage_14d_in_currency": "14 days",
        "price_change_percentage_30d_in_currency": "30 days",
        "price_change_percentage_60d_in_currency": "60 days",
        "price_change_percentage_1y_in_currency": "1 year"
    }

    timeframe = timeframe_map.get(metric, "specified period")

    lines = [f"Top {top_n} performers over {timeframe}:"]

    for i, coin in enumerate(coins[:top_n], 1):
        name = coin.get("name", "Unknown")
        symbol = coin.get("symbol", "").upper()
        price = coin.get("current_price", 0)
        change = coin.get(metric, 0)
        volume = coin.get("total_volume", 0)

        price_str = format_price(price)
        change_str = f"{change:+.2f}%" if change is not None else "N/A"
        volume_str = f"${volume:,.0f}"

        lines.append(f"{i}. {name} ({symbol}): {price_str}, {change_str}, Vol: {volume_str}")

    return "\n".join(lines)


def format_comparison_summary(comparisons: List[Dict]) -> str:
    """
    Format multi-coin comparison into technical summary.

    Args:
        comparisons: List of dicts with coin_id, name, symbol, start_price, end_price,
                     start_date, end_date, absolute_change, percentage_change

    Returns:
        Formatted comparison text
    """
    if not comparisons:
        return "No comparison data available"

    first = comparisons[0]
    lines = [f"Price comparison from {first.get('start_date')} to {first.get('end_date')}:"]

    for comp in comparisons:
        name = comp.get("name", comp.get("coin_id", "Unknown"))
        symbol = comp.get("symbol", "").upper()
        start_price = comp.get("start_price", 0)
        end_price = comp.get("end_price", 0)
        percentage_change = comp.get("percentage_change", 0)

        start_str = format_price(start_price)
        end_str = format_price(end_price)
        change_str = f"{percentage_change:+.2f}%"

        lines.append(f"{name} ({symbol}): {start_str} → {end_str} ({change_str})")

    return "\n".join(lines)


def sort_by_metric(coins: List[Dict], metric: str, reverse: bool = True) -> List[Dict]:
    """
    Sort coins by a specific metric field.

    Args:
        coins: List of coin dictionaries
        metric: Field name to sort by
        reverse: True for descending order (default), False for ascending

    Returns:
        Sorted list of coins
    """
    return sorted(
        coins,
        key=lambda x: x.get(metric, 0) if x.get(metric) is not None else float('-inf'),
        reverse=reverse
    )
