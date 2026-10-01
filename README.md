# Amazon_shopping_assistant
Playwright-based Amazon product search, filtering, and information extraction bot.

# Amazon Shopping Assistant

A Python-based automation tool built with Playwright that searches Amazon products, extracts product information, and filters products based on user-defined requirements.

## Features

- 🔍 Searches Amazon for user-specified products
- 📦 Extracts product titles and details
- 🧵 Checks material composition
- 📏 Checks available sizes
- 💰 Extracts product prices when available
- ✅ Identifies products matching the required criteria
- 🟢 Highlights matching products on the Amazon search page
- 🌐 Uses Playwright for browser automation

## Technologies Used

- Python
- Playwright
- Web Automation
- HTML/CSS Selectors

## How It Works

1. The bot searches Amazon for a specified product.
2. It collects products from the search results.
3. Each product is opened individually.
4. Required information is extracted from the product page.
5. The extracted information is compared with the user's requirements.
6. Products that satisfy the requirements are identified and highlighted on the search page.

## Example

The bot can search for products based on requirements such as:

**Product:** Polo T-Shirt  
**Material:** 100% Cotton  
**Size:** XL  

The bot checks individual product pages, extracts the available information, and identifies products that match the specified requirements.

## Installation

Clone the repository:

bash
git clone https://github.com/RohanAnand1705/Amazon_shopping_assistant.git
cd Amazon_shopping_assistant

Install the required dependencies:
pip install playwright

Install Playwright browsers:
playwright install

Run the Python script:
python amazon_bot.py

This project is intended for educational purposes and demonstrates browser automation and web scraping techniques using Playwright.
