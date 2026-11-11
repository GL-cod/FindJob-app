from datetime import date, timedelta, datetime
from zoneinfo import ZoneInfo
import requests, json
import time

import logging

log = logging.getLogger(__name__)


BF_API_MAX_RETRIES = 5
BF_RETRY_WAIT = 5

def base_payload(skip, limit=50):
    return {
        "limit": limit,
        "skip": skip,
        "sort": ["0"],
        "activitySectorId": [],
        "companiesSizes": [],
        "countriesIds": [],
        "entreprisesIds": [0],
        "geographicZones": [],
        "missionStartDate": None,
        "missionsDurations": [],
        "missionsTypesIds": [],
        "query": None,
        "specializationsIds": [],
        "studiesLevelId": [],
    }


def sort_offers_by_date(offers, reverse=True):
    return dict(
        sorted(
            offers.items(),
            key=lambda item: datetime.fromisoformat(
                item[1]["startBroadcastDate"]
            ),
            reverse=reverse,
        )
    )


def cutoff_date(max_days):
    today = datetime.now(ZoneInfo("Europe/Paris")).date()
    return today - timedelta(days=max_days)


def business_france_call_request(url, payload, headers):
    attempts = 0
    while attempts < BF_API_MAX_RETRIES:
        try:
            r = requests.post(
                url=url,
                json=payload,
                headers=headers,
                timeout=30,
            )
            r.raise_for_status()

            return r.json().get("result", [])
        
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 401:
                log.error(
                    f"BF API ERROR - Invalid API key (HTTP {e.response.status_code}: {e.response.text})",
                )
            else:
                log.error(
                    f"BF API ERROR - HTTP {e.response.status_code}: {e.response.text} "
                )
            raise

        except requests.exceptions.JSONDecodeError:
            log.error("BF API ERROR - Business France API returned invalid JSON.")
            raise

        except requests.exceptions.Timeout:
            attempts += 1 
            log.warning(
                f"Business France API timed out attempt {attempts}/{BF_API_MAX_RETRIES}. Retrying in {BF_RETRY_WAIT} seconds..."
            )
            time.sleep(BF_RETRY_WAIT)

        except requests.exceptions.ConnectionError:
            attempts += 1 
            log.warning(
                f"Unable to connect to the Business France API {attempts}/{BF_API_MAX_RETRIES}. Retrying in {BF_RETRY_WAIT} seconds..."
            )
            time.sleep(BF_RETRY_WAIT)

    raise RuntimeError(f"Business France API request failed after {BF_API_MAX_RETRIES} retries.")



def scrape_offers(config_dict, since, stored, batch=200):
    offers = {}

    stop = False
    skip = 0
    while not stop:
        data = business_france_call_request(
            url=config_dict["SEARCH_URL"],
            payload=base_payload(skip=skip, limit=batch),
            headers=config_dict["HEADERS"],
        )

        if not data:
            log.warning(f"Unexpected scraped data: {data}")
            break

        batch_had_new = False

        for dic in data:

            startBroadcastDate = datetime.fromisoformat(
                dic["startBroadcastDate"].replace("Z", "+00:00")
            ).date()

            # offers within a batch are not sorted by date: finish this batch but don't store the old offers ('continue')
            # but do not request the next (older) one: stop=True
            if startBroadcastDate < since:
                stop = True
                continue

            offer_id = str(dic["id"])
            if offer_id not in stored:
                batch_had_new = True 

            offers[str(dic["id"])] = {
                "organizationName": dic.get("organizationName"),
                "missionTitle": dic.get("missionTitle"),
                "cityName": dic.get("cityName"),
                "countryName": dic.get("countryName"),
                "missionDescription": dic.get("missionDescription"),
                "missionProfile": dic.get("missionProfile"),
                "startBroadcastDate": str(startBroadcastDate),
                "relevancy_check": "unchecked"
            }
            
        if not batch_had_new:          
            stop = True

        skip += batch

    offers = sort_offers_by_date(offers)

    return offers