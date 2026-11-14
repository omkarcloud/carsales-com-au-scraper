# 🚗 Carsales Com Au Scraper

Carsales Com Au Scraper is a **free and open-source** scraper that gets you **unlimited** detailed carsales.com.au data for free.

## ✨ What Can I Get?

- 🚗 **Full details on 200K+ cars for sale** — price with on-road costs, specs, seller phone, suburb & every photo
- 🔍 **Search 200K+ cars with 23 filters** — make, model, price, year, km, body, fuel, state & 9 sort orders
- 🏷️ **All 147 makes and every model** — live counts of cars for sale, plus every filter value with counts
- 📈 **Model research for every model year** — indicative price range, badges, price by year, FAQs & expert reviews

## 🏎️ Example: A Full carsales.com.au Listing

```json
{
  "id": "OAG-AD-26356625",
  "link": "https://www.carsales.com.au/cars/details/2020-ford-mustang-shelby-gt500-auto-rwd/OAG-AD-26356625/",
  "title": "2020 Ford Mustang Shelby GT500 Auto RWD",
  "year": 2020,
  "make": "Ford",
  "model": "Mustang",
  "badge": "Shelby GT500",
  "price": {
    "amount": 289990,
    "currency": "AUD",
    "type": "excluding_government_charges",
    "breakdown": [
      { "name": "Stamp Duty", "amount": 26100, "kind": "charge", "is_government_charge": true },
      { "name": "Estimated Drive Away Price (DAP)", "amount": 316138, "kind": "total", "is_estimate": true }
    ]
  },
  "odometer_km": 11587,
  "body_type": "Coupe",
  "engine": "8 cylinders, Petrol Supercharged Intercooled, 5.2L",
  "exterior_colour": "Blue",
  "location": { "suburb": "Port Melbourne", "region": "Melbourne", "state": "VIC", "postcode": "3207" },
  "seller": { "type": "dealer", "phone": "(03) 9188 4333", "member_since": 2017, "listings_count": 107 },
  "description": "FORD MUSTANG SHELBY GT500 5.2L V8 Supercharged 2020 ( 760hp and 847Nm ), this is the very last and already a future collectable…",
  "specifications": [
    { "category": "Engine", "items": [{ "name": "Power", "value": "566.7kW" }, { "name": "Engine Code", "value": "Coyote" }] }
  ],
  "image_count": 36,
  "images": ["https://carsales.pxcrush.net/carsales/cars/dealer/1hvzw1fcd72gk4t4g4s7s3drn.jpg"]
}
```

*Trimmed for readability.*

## 🚀 Unlimited Free carsales.com.au Data — Get It in 60 Seconds

1️⃣ Clone and install:
```bash
git clone https://github.com/omkarcloud/carsales-com-au-scraper
cd carsales-com-au-scraper
python -m pip install -r requirements.txt
```

2️⃣ Start the API:
```bash
python run.py
```

3️⃣ Get your first data:
```bash
curl "http://localhost:8000/cars/details?car=OAG-AD-26356625"
```

```json
{
  "id": "OAG-AD-26356625",
  "link": "https://www.carsales.com.au/cars/details/2020-ford-mustang-shelby-gt500-auto-rwd/OAG-AD-26356625/",
  "title": "2020 Ford Mustang Shelby GT500 Auto RWD",
  "year": 2020,
  "make": "Ford",
  "model": "Mustang",
  "badge": "Shelby GT500",
  "price": { "amount": 289990, "currency": "AUD", "type": "excluding_government_charges", "label": "Excl. Govt. Charges" },
  "odometer_km": 11587,
  "body_type": "Coupe",
  "transmission": "Automatic",
  "engine": "8 cylinders, Petrol Supercharged Intercooled, 5.2L",
  "exterior_colour": "Blue",
  "location": { "suburb": "Port Melbourne", "region": "Melbourne", "state": "VIC", "postcode": "3207" },
  "seller": { "id": "AGC-SELLER-10428", "type": "dealer", "phone": "(03) 9188 4333", "member_since": 2017, "listings_count": 107 }
}
```

All 6 endpoints are now live at `http://localhost:8000`.

carsales.com.au sits behind DataDome, and the scraper passes it over plain HTTP — no browser needed. From a home or office connection you need nothing else. On a cloud server, set `CARSALES_COM_AU_PROXY` to a residential proxy (`http://user:pass@host:port`) — Australian works best. Outside Australia, set `CARSALES_COM_AU_PRICE_PROXY` to an Australian residential proxy to get the on-road price breakdown — it is used for that one small call only. If you get blocked, set `CARSALES_COM_AU_FALLBACK_PROXY` and the scraper switches to it for 10 minutes after each block.

## 📚 Endpoints

6 endpoints cover everything you need.

| Endpoint | Path | Returns |
|---|---|---|
| Car Details | `/cars/details` | Everything about one car in a single call, every photo included |
| Search Cars | `/cars/search` | 22 cars per page with 23 filters and 9 sort orders |
| List Makes | `/makes/list` | All 147 makes with live counts of cars for sale |
| List Models | `/models/list` | Every model of a make with live counts |
| List Filter Values | `/cars/filters` | Every value of a search filter with live match counts |
| Model Details | `/models/details` | Price range, badges, price by year, FAQs and expert review |

## 🔍 Exploring Parameters

The same API is published on RapidAPI, and its playground is the easiest place to try parameters and see raw responses. Once a request looks right, run it locally for **unlimited free** data.

1. [Subscribe to the free plan](https://rapidapi.com/OmkarCloud/api/best-carsales-com-au-scraper-free-1000-calls/pricing) — 1,000 calls/month, no credit card.
2. [Try the endpoints in the playground](https://rapidapi.com/OmkarCloud/api/best-carsales-com-au-scraper-free-1000-calls/playground) — every param is pre-filled, so you see real data in one click.
3. Copy the generated code and replace `https://best-carsales-com-au-scraper-free-1000-calls.p.rapidapi.com` with `http://localhost:8000`. It will now run against your local API.

```python
import requests

# generated by the playground, host swapped for the local API
response = requests.get(
    "http://localhost:8000/cars/search",
    params={"make": "Ford", "model": "Mustang", "state": "vic", "sort": "price_low_to_high"},
)
print(response.json())
```

## 💬 Have Questions? We Have Answers.

You're a developer — we know how hard completing a project can be. So we offer full support: just message us and we'll reply ✅ with a solution within 1 working day.

[![Message Us on WhatsApp about Carsales Com Au Scraper](https://raw.githubusercontent.com/omkarcloud/assets/master/images/whatsapp-us.png)](https://www.omkar.cloud/l/carsales-com-au-scraper-github-whatsapp)

[![Ask Us by Email about Carsales Com Au Scraper](https://raw.githubusercontent.com/omkarcloud/assets/master/images/ask-on-email.png)](mailto:happy.to.help@omkar.cloud?subject=Help%20with%20Carsales%20Com%20Au%20Scraper%20API&body=I%20need%20help%20using%20the%20Carsales%20Com%20Au%20Scraper%20API.)

## ⚡ Popular Scrapers by Omkar Cloud

- [**Google Maps Scraper (3,100+ GitHub Stars)**](https://github.com/omkarcloud/google-maps-scraper) — type "dentists in New York", get every business as a ready-to-call lead list: phones, emails, websites & reviews. Up to 100K free leads/month.
- [**G2 Scraper**](https://www.omkar.cloud/tools/g2-scraper) — G2 product details, ratings & AI-found contacts
- [**Website Email Contact Scraper**](https://www.omkar.cloud/tools/website-email-contact-scraper) — emails, phones & socials from any website
- [**AliExpress Scraper**](https://www.omkar.cloud/tools/aliexpress-scraper-api) — live product details, SKU variants, stock & shipping
- [**Booking Scraper**](https://www.omkar.cloud/tools/booking-scraper) — Booking.com hotels: prices, ratings, rooms & amenities
- [**Etsy Scraper**](https://www.omkar.cloud/tools/etsy-scraper) — Etsy products: prices, discounts, shops & variations

## ⭐ Love It? [Star It ⭐!](https://github.com/omkarcloud/carsales-com-au-scraper)

Star the repo ⭐ and become my star hero!

It's just 1 click, but it means the world to me.

[![Star us on GitHub](https://raw.githubusercontent.com/omkarcloud/google-maps-scraper/master/screenshots/star-us.png)](https://github.com/omkarcloud/carsales-com-au-scraper)
