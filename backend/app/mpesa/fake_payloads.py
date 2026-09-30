"""Builds callback bodies shaped like the ones Safaricom posts. Used by tests and scripts/demo_flow.py."""
import uuid


def stk_success(checkout_request_id: str, amount_kes: int, phone: str = "254712345678", receipt: str | None = None) -> dict:
    # Safaricom's sandbox commonly returns this exact fixed example receipt (it's their own docs example)
    # on every simulated push, rather than a fresh one per transaction like production does. Defaulting
    # to it here - instead of a random value - is what actually caught the uniqueness bug this fixes.
    receipt = receipt or "NLJ7RT61SV"
    return {"Body": {"stkCallback": {
        "MerchantRequestID": "m-" + uuid.uuid4().hex[:6], "CheckoutRequestID": checkout_request_id,
        "ResultCode": 0, "ResultDesc": "The service request is processed successfully.",
        "CallbackMetadata": {"Item": [
            {"Name": "Amount", "Value": amount_kes},
            {"Name": "MpesaReceiptNumber", "Value": receipt},
            {"Name": "TransactionDate", "Value": 20260922101500},
            {"Name": "PhoneNumber", "Value": int(phone)}]}}}}


def stk_failure(checkout_request_id: str, code: int = 1032, desc: str = "Request cancelled by user") -> dict:
    return {"Body": {"stkCallback": {"MerchantRequestID": "m-x", "CheckoutRequestID": checkout_request_id,
                                     "ResultCode": code, "ResultDesc": desc}}}


def b2c_result(originator_id: str, conversation_id: str, amount_kes: int, ok: bool = True, code: int = 2001,
               desc: str = "The initiator information is invalid.") -> dict:
    result = {"ResultType": 0, "ResultCode": 0 if ok else code,
              "ResultDesc": "The service request is processed successfully." if ok else desc,
              "OriginatorConversationID": originator_id, "ConversationID": conversation_id,
              "TransactionID": "QKB" + uuid.uuid4().hex[:8].upper()}
    if ok:
        result["ResultParameters"] = {"ResultParameter": [
            {"Key": "TransactionAmount", "Value": amount_kes},
            {"Key": "TransactionReceipt", "Value": result["TransactionID"]}]}
    return {"Result": result}


def b2c_timeout(originator_id: str, conversation_id: str) -> dict:
    return {"Result": {"ResultType": 1, "ResultCode": 1, "ResultDesc": "The service request timed out.",
                       "OriginatorConversationID": originator_id, "ConversationID": conversation_id}}