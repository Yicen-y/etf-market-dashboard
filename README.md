# ETF Market Dashboard

Python + ETFirst + ECharts dashboard for comparing the 300 dividend ETF, 300 growth ETF, and HS300 ETF.

## Local use

Install the CLI and dependencies:

```powershell
python -m pip install -r requirements.txt
python -m pip install https://www.nffund.com/wxfiles/miniapp/openu/static/assets/etfirst/0.4.2/etfirst-0.4.2.tar.gz
etfirst auth login --api-key <YOUR_KEY>
python -m scripts.update_data
```

Start the local site from the repository root:

```powershell
python -m http.server 8000
```

Open `http://localhost:8000/web/`.

## GitHub setup

1. Create a private repository named `etf-market-dashboard`.
2. Add the repository secret `ETFIRST_API_KEY`.
3. Enable GitHub Pages with the GitHub Actions source.
4. Run the `Update ETF dashboard` workflow manually once.

The scheduled workflow runs at 16:30 China Standard Time on weekdays. GitHub schedule timing can be delayed; the page always displays the latest actual trading date and update time.

## Benchmark behavior

The default benchmark is 2025-12-31. The date picker accepts any date. If the selected date is not a trading day, the dashboard uses the latest trading date not after the selection and shows the actual date used.

## Data and security

The frontend reads committed `data/etf_prices.json`. The API Key is used only by GitHub Actions and is never sent to the browser. Missing prices remain missing and are not converted to zero.

