import requests
class FHIRClient:
    FHIR_VERSION = "R4"
    def __init__(self, base_url: str, token: str):
        self.base_url = base_url
        self.headers = {"Authorization": f"Bearer {token}",
                        "Content-Type": "application/fhir+json"}
    def get_patient(self, patient_id: str) -> dict:
        r = requests.get(f"{self.base_url}/Patient/{patient_id}", headers=self.headers)
        r.raise_for_status()
        return r.json()
