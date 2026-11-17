"""Published network schedules, reviewed 2026-11-17.

These are editable suggestions for Flat Rates meter tariffs, not Mercury's
retail billing rules. Do not substitute controlled-load or multi-period ToU
hours for a day/night register schedule. Sources without a verified compatible
schedule deliberately have no defaults. Updating this catalogue must never
change a saved meter schedule.
"""

from dataclasses import dataclass

REVIEWED = "2026-11-17"
MANUAL = "manual"


@dataclass(frozen=True)
class NetworkTariff:
    label: str
    source: str
    note: str
    night_start: str | None = None
    night_end: str | None = None
    weekend_night: bool = False

    @property
    def defaults(self) -> dict:
        if self.night_start is None:
            return {}
        return {
            "night_start": self.night_start,
            "night_end": self.night_end,
            "weekend_night": self.weekend_night,
        }


# Keep network/region and tariff variants explicit; geography alone cannot
# identify a customer's meter configuration. URLs identify the evidence used,
# including when the current publication does not establish day/night hours.
NETWORK_TARIFFS = {
    "alpine": NetworkTariff(
        "Alpine Energy — South Canterbury — Day/Night",
        "https://www.alpineenergy.co.nz/customers/pricing/price-update-as-of-1-april-2026",
        "2026/27 Day/Night: night 23:00–07:00 daily.",
        "23:00",
        "07:00",
    ),
    "aurora": NetworkTariff(
        "Aurora Energy — Dunedin, Central Otago, Queenstown/Wānaka",
        "https://www.auroraenergy.co.nz/media/ohyldwer/aurora-energy-use-of-system-pricing-methodology-1-april-2026.pdf",
        "2026 ToU peaks: 07:00–12:00 and 17:00–22:00 daily. "
        "Multiple daily periods cannot be represented by these day/night fields.",
    ),
    "buller": NetworkTariff(
        "Buller Electricity — Westport/Karamea",
        "https://bullerelectricity.co.nz/wp-content/uploads/BEL-Pricing-Guide-2026-27-1.pdf",
        "The 2026/27 guide lists Day/Night prices but does not specify the hours. "
        "Enter confirmed hours manually.",
    ),
    "centralines": NetworkTariff(
        "Centralines — Central Hawke’s Bay — Day/Night",
        "https://www.centralines.co.nz/media/extdcb1c/cl-cm0002-centralines-pricing-policy-and-schedules-2026-to-2027.pdf",
        "2026/27 section 2.4: night 23:00–07:00 daily, local time including daylight saving. "
        "This is the Day/Night option, not the separate ToU schedule.",
        "23:00",
        "07:00",
    ),
    "counties": NetworkTariff(
        "Counties Energy — Franklin/south Auckland/north Waikato",
        "https://assets.countiesenergy.co.nz/app/uploads/2026/03/02093429/2026-27-Price-Schedule.pdf",
        "2026/27 ToU peaks: weekdays 07:00–11:00 and 17:00–21:00; off-peak otherwise. "
        "Multiple daily periods cannot be represented by these day/night fields.",
    ),
    "ea_networks": NetworkTariff(
        "EA Networks — Ashburton — Day/Night & Weekend",
        "https://web-assets.eanetworks.co.nz/f/285789107945704/x/c36bd36945/ea-networks-pricing-methodology-fy2027-draft.pdf",
        "The published 2026/27 methodology uses weekday day hours 07:00–21:00, "
        "with night/weekend pricing outside them.",
        "21:00",
        "07:00",
        True,
    ),
    "electra": NetworkTariff(
        "Electra — Kāpiti/Horowhenua",
        "https://electra.co.nz/wp-content/uploads/2026/09/Electra-Pricing-Schedule-FY2627.pdf",
        "2026/27 ToU peaks: weekdays 07:00–11:00 and 17:00–21:00; off-peak otherwise. "
        "The older Day/Night schedule is not used as a current default.",
    ),
    "invercargill": NetworkTariff(
        "Electricity Invercargill — Invercargill/Bluff",
        "https://powernet.co.nz/wp-content/uploads/2026/03/EIL-2026-Residential-and-General-Delivery-Prices-pricesV2.pdf",
        "2026 pricing separates peak (07:00–11:00, 17:00–21:00), shoulder and night. "
        "Three rates cannot be represented by these day/night fields.",
    ),
    "firstlight": NetworkTariff(
        "Firstlight Network — Gisborne/Wairoa",
        "https://firstlightnetwork.co.nz/tell-me-about/home-energy-hub/latest-network-pricing",
        "2026 ToU peaks: weekdays 07:00–11:00 and 17:00–21:00; off-peak otherwise. "
        "Multiple daily periods cannot be represented by these day/night fields.",
    ),
    "horizon": NetworkTariff(
        "Horizon Networks — Eastern Bay of Plenty",
        "https://cdn.sanity.io/files/i6v1mrdi/production/f70649503cd1a30715c41d9334ecc4bc7b67a9eb.pdf",
        "2026/27 ToU: peak 07:00–11:00/17:00–21:00, shoulder 11:00–17:00/21:00–22:00, "
        "off-peak 22:00–07:00 daily. Three rates cannot be represented by these fields.",
    ),
    "mainpower": NetworkTariff(
        "MainPower — North Canterbury",
        "https://www.mainpower.co.nz/wp-content/uploads/2026/03/2026-2027-Pricing-Methodology.pdf",
        "The published 21:30–07:30 option is controlled night-only storage heating, "
        "not a whole-meter Day/Night tariff. Enter confirmed hours manually.",
    ),
    "marlborough": NetworkTariff(
        "Marlborough Lines — Marlborough",
        "https://static1.squarespace.com/static/61303f01fe6fe601f2de1553/t/699e189de251470d203e672a/1771968669487/WEB_2026%2BPrice%2BSchedule.pdf",
        "The 2026 residential schedule includes peak/off-peak and controlled night-only "
        "options. No compatible whole-meter day/night hours verified; enter them manually.",
    ),
    "tasman": NetworkTariff(
        "Network Tasman — Tasman — Day/Night",
        "https://networktasman.co.nz/wp-content/uploads/2026/05/Network-Tasman-Limited-pricing-schedule-and-policy-April-2026.pdf",
        "2026/27 Day/Night category: night 23:00–07:00 daily. "
        "Select Nelson separately for the former Nelson Electricity network.",
        "23:00",
        "07:00",
    ),
    "nelson": NetworkTariff(
        "Network Tasman — Nelson city (formerly Nelson Electricity)",
        "https://networktasman.co.nz/wp-content/uploads/2026/05/Network-Tasman-Limited-pricing-schedule-and-policy-April-2026.pdf",
        "2026/27 Nelson pricing has peak 07:00–23:00 weekdays and off-peak otherwise, "
        "including all weekends. The Day/Night category is explicitly unavailable in Nelson; "
        "enter hours only if confirmed for your Mercury meter tariff.",
    ),
    "waitaki": NetworkTariff(
        "Network Waitaki — North Otago — Day/Night",
        "https://www.networkwaitaki.co.nz/assets/Disclosures/FY27-Pricing-Methodology.pdf",
        "2026/27 section 5.4: night 23:00–07:00 daily. "
        "Confirm that your retailer uses these periods for your meter tariff.",
        "23:00",
        "07:00",
    ),
    "northpower": NetworkTariff(
        "Northpower — Whangārei/Kaipara",
        "https://northpower.nz/wp-content/uploads/2026/02/Northpower-FY27-Pricing-Policy.pdf",
        "2026/27 ToU has peak, shoulder and off-peak periods (overnight 22:00–07:00). "
        "The separate 23:00–07:00 Night option is controlled supply. Neither is a simple Day/Night default.",
    ),
    "orion": NetworkTariff(
        "Orion — Central Canterbury — Day/Night (S9)",
        "https://www.oriongroup.co.nz/assets/Be-prepared/NW702602.pdf",
        "NW70.26.02 S9: day/night meter switching, night 21:00–07:00 daily. "
        "Check the meter/register configuration and time basis.",
        "21:00",
        "07:00",
    ),
    "orion_weekend": NetworkTariff(
        "Orion — Central Canterbury — Day/Night & Weekend (S10)",
        "https://www.oriongroup.co.nz/assets/Be-prepared/NW702602.pdf",
        "NW70.26.02 S10: night 21:00–07:00 plus all Saturday/Sunday. "
        "Check the meter/register configuration and time basis.",
        "21:00",
        "07:00",
        True,
    ),
    "otagonet": NetworkTariff(
        "OtagoNet — rural Otago",
        "https://powernet.co.nz/wp-content/uploads/2026/02/OJV-2026-Residential-and-General-Delivery-Prices.pdf",
        "2026 pricing has peak 07:00–11:00/17:00–21:00, shoulder 11:00–17:00/21:00–23:00 "
        "and night 23:00–07:00 daily. Three rates cannot be represented by these fields.",
    ),
    "powerco": NetworkTariff(
        "Powerco — Taranaki, Whanganui, Manawatū, Wairarapa, Bay of Plenty, Thames Valley",
        "https://www.powerco.co.nz/-/media/project/powerco/powerco-documents/who-we-are---pricing-and-disclosures/pricing/electricity-pricing/3-electricity-pricing-methodology-and-schedules/12---1-april-2026---31-march-2027/fy27-powerco-pricing-policy.pdf",
        "2026/27 ToU uses multiple daily peak/off-peak periods, with regional/weekend variants. "
        "23:00–07:00 is controlled night supply, not a whole-meter Day/Night default.",
    ),
    "scanpower": NetworkTariff(
        "Scanpower — Dannevirke/southern Hawke’s Bay",
        "https://scanpower.co.nz/wp-content/uploads/2026/03/Scanpower-Limited-Network-Pricing-Methodology-Disclosure-2026-2027.pdf",
        "2026/27 domestic off-peak: 23:00–07:00 weekdays, all weekends and public holidays. "
        "Public-holiday exceptions are not supported by these fields; no automatic default.",
    ),
    "power_company": NetworkTariff(
        "The Power Company — Southland/West Otago",
        "https://powernet.co.nz/wp-content/uploads/2026/02/TPCL-2026-GST-Exclusive-Residential-and-General-Delivery-Prices.pdf",
        "2026 pricing separates peak (07:00–11:00, 17:00–21:00), shoulder and night. "
        "Three rates cannot be represented by these day/night fields.",
    ),
    "top_energy": NetworkTariff(
        "Top Energy — Far North",
        "https://topenergy.co.nz/assets/TARD26-Pricing-Schedule-FINAL.pdf",
        "2026 ToU has peak, shoulder and off-peak periods (overnight 22:00–07:00), "
        "with weekend/holiday exceptions. Three rates cannot be represented by these fields.",
    ),
    "lines_company": NetworkTariff(
        "The Lines Company — King Country",
        "https://www.thelinescompany.co.nz/site/uploads/2026/03/Pricing-Schedule-Non-WESCT-RY2027-1.pdf",
        "The current schedule has multiple ToU periods. No compatible Day/Night default; "
        "enter your confirmed meter-tariff hours manually.",
    ),
    "unison": NetworkTariff(
        "Unison — Hawke’s Bay, Rotorua, Taupō — Day/Night",
        "https://www.unison.co.nz/tell-me-about/unison-group/publications-disclosures/pricing-information/guide-to-unison-pricing/",
        "Published Day/Night option: night 23:00–07:00 daily, local time including daylight saving. "
        "This is not the separate ToU schedule.",
        "23:00",
        "07:00",
    ),
    "vector": NetworkTariff(
        "Vector — Auckland",
        "https://media.vector.co.nz/production/documents/electricitypricescheduleseffectivefrom1april2026.pdf",
        "2026 peak windows vary by season: 07:00–11:00 June–August and 17:00–22:00 "
        "May–September, every day. Seasonal and multiple daily periods cannot fit these fields.",
    ),
    "waipa": NetworkTariff(
        "Waipā Networks — Te Awamutu/Cambridge",
        "https://waipanetworks.co.nz/about/document-library/disclosures-pricing/lines-charges-2/",
        "ToU peaks: 07:00–09:30 and 17:30–20:00; off-peak 22:00–07:00; shoulder otherwise. "
        "Three rates cannot fit these fields. Night-only controlled supply is a separate option.",
    ),
    "wel": NetworkTariff(
        "WEL Networks — Hamilton/north Waikato/Raglan",
        "https://www.wel.co.nz/media/b4fflnhu/price-schedule-2026.pdf",
        "2026 ToU: workday peaks 07:00–09:30/17:30–20:00; off-peak 22:00–07:00; "
        "shoulder otherwise. Weekend/holiday daytime is shoulder. Three rates cannot fit these fields.",
    ),
    "wellington": NetworkTariff(
        "Wellington Electricity — Wellington/Hutt Valley/Porirua",
        "https://www.welectricity.co.nz/disclosures/pricing/time-of-use-pricing",
        "ToU peaks: weekdays 07:00–11:00 and 17:00–21:00; off-peak otherwise. "
        "Multiple daily periods cannot be represented by these day/night fields.",
    ),
    "westpower": NetworkTariff(
        "Westpower — West Coast — Day/Night",
        "https://cdn.sanity.io/files/uy55ipiu/public_content/61e3f9e24a9798026bbe4bc789960d8739e8e37d.pdf",
        "2026 methodology: night 23:00–07:00 daily. "
        "The methodology proposes a different ToU structure for 2027.",
        "23:00",
        "07:00",
    ),
}
