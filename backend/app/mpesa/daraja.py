"""Safaricom Daraja client. MockDaraja needs no credentials; RealDaraja talks to the sandbox/production API."""
import base64
import time
import uuid
from datetime import datetime, timedelta, timezone

import httpx

from app.config import settings


_EAT = timezone(timedelta(hours=3))   # Kenya time (no DST). Servers like Vercel run in UTC.


def _timestamp() -> str:
    return datetime.now(_EAT).strftime("%Y%m%d%H%M%S")


class DarajaError(Exception):
    """definitive=True  -> Safaricom clearly rejected the request (safe to refund/reverse).
    definitive=False -> outcome unknown (timeout etc). Do NOT refund automatically."""

    def __init__(self, message: str, definitive: bool):
        super().__init__(message)
        self.definitive = definitive


class MockDaraja:
    def stk_push(self, *, phone, amount_kes, account_ref, description, callback_url) -> dict:
        return {"MerchantRequestID": f"mock-m-{uuid.uuid4().hex[:10]}",
                "CheckoutRequestID": f"ws_CO_mock_{uuid.uuid4().hex[:16]}",
                "ResponseCode": "0", "ResponseDescription": "Success. Request accepted for processing",
                "CustomerMessage": "Success. Request accepted for processing"}

    def stk_query(self, checkout_request_id: str) -> dict:
        return {"ResponseCode": "0", "ResultCode": "1037", "ResultDesc": "Mock: no result yet"}

    def b2c(self, *, originator_conversation_id, phone, amount_kes, remarks, result_url, timeout_url) -> dict:
        return {"ConversationID": f"AG_mock_{uuid.uuid4().hex[:14]}",
                "OriginatorConversationID": originator_conversation_id,
                "ResponseCode": "0", "ResponseDescription": "Accept the service request successfully."}


    def transaction_status(self, *, receipt, originator_conversation_id, result_url, timeout_url) -> dict:
        return {"ConversationID": f"AG_mock_{uuid.uuid4().hex[:14]}", "OriginatorConversationID": uuid.uuid4().hex,
                "ResponseCode": "0", "ResponseDescription": "Accept the service request successfully."}

    def account_balance(self, *, result_url, timeout_url) -> dict:
        return {"ConversationID": f"AG_mock_{uuid.uuid4().hex[:14]}", "OriginatorConversationID": uuid.uuid4().hex,
                "ResponseCode": "0", "ResponseDescription": "Accept the service request successfully."}


class RealDaraja:
    def __init__(self):
        self._token: str | None = None
        self._token_exp = 0.0

    # ---- auth -------------------------------------------------------------------------
    def _access_token(self) -> str:
        if self._token and time.time() < self._token_exp - 30:
            return self._token
        try:
            r = httpx.get(f"{settings.mpesa_base_url}/oauth/v1/generate",
                          params={"grant_type": "client_credentials"},
                          auth=(settings.mpesa_consumer_key, settings.mpesa_consumer_secret), timeout=20)
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise DarajaError(f"Could not get Daraja token: {e}", definitive=True)
        data = r.json()
        self._token = data["access_token"]
        self._token_exp = time.time() + int(data.get("expires_in", 3599))
        return self._token

    def _post(self, path: str, body: dict, *, money_out: bool) -> dict:
        headers = {"Authorization": f"Bearer {self._access_token()}"}
        try:
            r = httpx.post(f"{settings.mpesa_base_url}{path}", json=body, headers=headers, timeout=25)
        except httpx.ConnectError as e:                       # never reached Safaricom
            raise DarajaError(f"Connection failed: {e}", definitive=True)
        except httpx.HTTPError as e:                          # sent, but no answer: unknown
            raise DarajaError(f"No response from Daraja: {e}", definitive=not money_out)
        if r.status_code >= 500:
            raise DarajaError(f"Daraja {r.status_code}: {r.text[:200]}", definitive=not money_out)
        try:
            data = r.json() if r.content else {}
        except ValueError:
            data = {}
            if r.status_code < 400:                           # 2xx but unreadable body: outcome unknown
                raise DarajaError(f"Unreadable Daraja response: {r.text[:200]}", definitive=not money_out)
        if r.status_code >= 400 or str(data.get("ResponseCode", "0")) != "0":
            raise DarajaError(f"Daraja rejected request: {data or r.text[:200]}", definitive=True)
        return data

    # ---- APIs -------------------------------------------------------------------------
    def stk_push(self, *, phone, amount_kes, account_ref, description, callback_url) -> dict:
        ts = _timestamp()
        password = base64.b64encode(f"{settings.mpesa_shortcode}{settings.mpesa_passkey}{ts}".encode()).decode()
        body = {"BusinessShortCode": settings.mpesa_shortcode, "Password": password, "Timestamp": ts,
                "TransactionType": settings.mpesa_transaction_type, "Amount": int(amount_kes),
                "PartyA": phone, "PartyB": settings.mpesa_party_b or settings.mpesa_shortcode, "PhoneNumber": phone,
                "CallBackURL": callback_url, "AccountReference": account_ref[:12],
                "TransactionDesc": description[:13]}
        return self._post("/mpesa/stkpush/v1/processrequest", body, money_out=False)

    def stk_query(self, checkout_request_id: str) -> dict:
        ts = _timestamp()
        password = base64.b64encode(f"{settings.mpesa_shortcode}{settings.mpesa_passkey}{ts}".encode()).decode()
        body = {"BusinessShortCode": settings.mpesa_shortcode, "Password": password, "Timestamp": ts,
                "CheckoutRequestID": checkout_request_id}
        return self._post("/mpesa/stkpushquery/v1/query", body, money_out=False)

    def _security_credential(self) -> str:
        if settings.mpesa_security_credential:      # e.g. the sandbox value Safaricom's portal hands out directly
            return settings.mpesa_security_credential
        from cryptography import x509
        from cryptography.hazmat.primitives.asymmetric import padding
        with open(settings.mpesa_cert_path, "rb") as f:
            raw = f.read()
        try:
            cert = x509.load_pem_x509_certificate(raw)
        except ValueError:
            cert = x509.load_der_x509_certificate(raw)
        enc = cert.public_key().encrypt(settings.mpesa_initiator_password.encode(), padding.PKCS1v15())
        return base64.b64encode(enc).decode()

    def b2c(self, *, originator_conversation_id, phone, amount_kes, remarks, result_url, timeout_url) -> dict:
        body = {"InitiatorName": settings.mpesa_initiator_name,
                "SecurityCredential": self._security_credential(),
                "CommandID": settings.mpesa_b2c_command, "Amount": int(amount_kes),
                "PartyA": settings.mpesa_b2c_shortcode or settings.mpesa_shortcode, "PartyB": phone, "Remarks": remarks[:100],
                "QueueTimeOutURL": timeout_url, "ResultURL": result_url, "Occasion": "QuickIQ payout"}
        if "/v3/" in settings.mpesa_b2c_path:        # only v3 accepts a caller-supplied unique ID
            body["OriginatorConversationID"] = originator_conversation_id
        return self._post(settings.mpesa_b2c_path, body, money_out=True)

    # ---- read-only helpers: answers arrive later on the ResultURL ----------------------
    def _initiator_body(self, command_id: str, remarks: str, result_url: str, timeout_url: str) -> dict:
        return {"Initiator": settings.mpesa_initiator_name, "SecurityCredential": self._security_credential(),
                "CommandID": command_id, "PartyA": settings.mpesa_b2c_shortcode or settings.mpesa_shortcode,
                "IdentifierType": "4", "Remarks": remarks, "QueueTimeOutURL": timeout_url, "ResultURL": result_url}

    def transaction_status(self, *, receipt, originator_conversation_id, result_url, timeout_url) -> dict:
        """Ask Safaricom what happened to a payout. Uses the M-Pesa receipt if we have one, otherwise the
        conversation id Safaricom gave us when the payout was accepted."""
        body = self._initiator_body("TransactionStatusQuery", "Withdrawal status check", result_url, timeout_url)
        body["Occasion"] = "QuickIQ"
        if receipt:
            body["TransactionID"] = receipt
        else:
            body["OriginatorConversationID"] = originator_conversation_id
        return self._post("/mpesa/transactionstatus/v1/query", body, money_out=False)

    def account_balance(self, *, result_url, timeout_url) -> dict:
        body = self._initiator_body("AccountBalance", "Balance check", result_url, timeout_url)
        return self._post("/mpesa/accountbalance/v1/query", body, money_out=False)


_client = None


def get_daraja():
    global _client
    if _client is None:
        _client = MockDaraja() if settings.mpesa_mode == "mock" else RealDaraja()
    return _client