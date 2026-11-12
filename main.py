"""Use the scraper straight from Python — no server needed.

    python main.py

Every function returns the same JSON the API does; results are written to
output/*.json. Params go through the same schemas the API uses, so defaults
are filled in and a listing id or link both work.
"""
import json
import os

from carsales_com_au import api, schemas

os.makedirs("output", exist_ok=True)


def save(name, data):
    path = os.path.join("output", name)
    with open(path, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"saved {path}")


def run(schema_cls, fn, **params):
    return fn(**schema_cls().load(params))


if __name__ == "__main__":
    # a listing id or any carsales.com.au listing link — price with on-road costs, specs, seller, every photo
    save("car_shelby_gt500.json",
         run(schemas.CarSchema, api.car_details, car="OAG-AD-26356625"))

    # 22 cars per page, filter by make, model, price, year, km, body, fuel, state and more
    save("search_ford_mustang.json",
         run(schemas.CarsSearchSchema, api.cars_search, make="Ford", model="Mustang"))

    # the model research page — indicative price range, badges, price by year, FAQs, expert review
    save("model_ford_mustang.json",
         run(schemas.ModelDetailsSchema, api.model_details, make="Ford", model="Mustang"))
