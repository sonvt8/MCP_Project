from typing import Any

import requests
import os
from mcp.server.fastmcp import FastMCP

PORT = int(os.getenv("PORT", "8897"))
mcp = FastMCP("Binance MCP", host="0.0.0.0", port=PORT)

def get_symbol_from_name(name: str) -> str:
    if name.lower() in ["bitcoin", "btc"]:
        return "BTCUSDT"
    elif name.lower() in ["ethereum", "eth"]:
        return "ETHUSDT"
    else:
        return name.upper()


@mcp.tool()
def get_price(symbol: str) -> Any:
    """
    Get the current price of a crypto asset from Binance

    Args:
        symbol (str): The symbol of the crypto asset to get the price of

    Returns:
        Any: The current price of the crypto asset
    """
    symbol = get_symbol_from_name(symbol)
    url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}"
    response = requests.get(url)
    response.raise_for_status()
    return response.json()


@mcp.tool()
def get_price_price_change(symbol: str) -> Any:
    """
    Get the price change of the last 24 hours of a crypto asset from Binance

    Args:
        symbol (str): The symbol of the crypto asset to get the price change of

    Returns:
        Any: The price change of the crypto asset in the last 24 hours
    """
    symbol = get_symbol_from_name(symbol)
    url = f"https://data-api.binance.vision/api/v3/ticker/24hr?symbol={symbol}"
    response = requests.get(url)
    response.raise_for_status()
    return response.json()


if __name__ == "__main__":
    # Access the MCP via the stdio protocol
    # mcp.run(transport="stdio")

    # Access the MCP via the SSE protocol thourgh <<server_url>>/sse
    mcp.run(transport="sse")

    # Access the MCP via the Streamable HTTP protocol thourgh <<server_url>>/streamable-http
    # mcp.run(transport="streamable-http")