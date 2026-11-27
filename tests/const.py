"""Static API payloads used by the tests."""

from __future__ import annotations

from typing import Any, Final

SCHOOL_LIST_PAYLOAD: Final[dict[str, Any]] = {
    "lastUpdated": "2023-12-05T08:39:19.743370813",
    "result": {
        "institutions": [
            {"id": 1274, "name": "Bonnier", "town": "Mercier"},
            {
                "id": 2874,
                "name": "Centre de formation des Maskoutains",
                "town": "Acton Vale",
            },
            {"id": 1197, "name": "à l’Orée-des-Bois", "town": "Drummondville"},
        ]
    },
    "success": True,
}

CLOSED_PAYLOAD: Final[dict[str, Any]] = {
    "lastUpdated": "05-12-2023 08:39:18",
    "result": {
        "institutions": [
            {
                "id": 1274,
                "institution_type": {"id": 8, "name": "École secondaire"},
                "name": "Bonnier",
                "town": "Mercier",
                "region": {"id": 14, "code": "14", "name": "Montérégie"},
                "parent": {
                    "id": 15,
                    "name": "Centre de services scolaire des Grandes-Seigneuries",
                    "region": {"id": 14, "code": "14", "name": "Montérégie"},
                },
                "closures": [
                    {
                        "id": 3441,
                        "state": "closed",
                        "datetime_start": "2017-01-24T05:53:31-05:00",
                        "datetime_end": "2017-01-24T20:45:00-05:00",
                        "closure_informations": [{"name": "Cours suspendus"}],
                    },
                    {
                        "id": 6719,
                        "state": "closed",
                        "datetime_start": "2023-12-05T05:00:00-05:00",
                        "message": "Le mardi 5 décembre, pour la journée",
                        "closure_informations": [
                            {"name": "Pas de transport pour la journée"}
                        ],
                    },
                ],
            }
        ]
    },
    "success": True,
}

EMPTY_CLOSED_PAYLOAD: Final[dict[str, Any]] = {
    "lastUpdated": "05-12-2023 09:00:00",
    "result": {"institutions": []},
    "success": True,
}

# Same school, but the current closure is bounded: used to check the
# "closure active right now" logic without depending on the system clock.
CLOSED_BOUNDED_PAYLOAD: Final[dict[str, Any]] = {
    "lastUpdated": "05-12-2023 08:39:18",
    "result": {
        "institutions": [
            {
                "id": 1274,
                "name": "Bonnier",
                "town": "Mercier",
                "region": {"id": 14, "name": "Montérégie"},
                "parent": {
                    "name": "Centre de services scolaire des Grandes-Seigneuries",
                    "region": {"id": 14, "name": "Montérégie"},
                },
                "closures": [
                    {
                        "id": 3441,
                        "state": "closed",
                        "datetime_start": "2017-01-24T05:53:31-05:00",
                        "datetime_end": "2017-01-24T20:45:00-05:00",
                        "closure_informations": [{"name": "Cours suspendus"}],
                    },
                    {
                        "id": 6719,
                        "state": "closed",
                        "datetime_start": "2023-12-05T05:00:00-05:00",
                        "datetime_end": "2023-12-05T20:45:00-05:00",
                        "message": "Le mardi 5 décembre, pour la journée",
                        "closure_informations": [
                            {"name": "Pas de transport pour la journée"}
                        ],
                    },
                ],
            }
        ]
    },
    "success": True,
}
