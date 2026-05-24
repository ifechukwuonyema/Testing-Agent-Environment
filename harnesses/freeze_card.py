"""
One-shot script: mints a cards token, signs a freeze request, freezes target card.
Usage: python freeze_card.py [cardId]
Defaults to the first candidate if no arg given.
"""
import hashlib, hmac, json, os, sys, time, uuid
import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

IAM_URL           = "https://hasham.platform.dev.chamsswitch.com/gateway/token"
CARDS_CLIENT_ID   = "platform-kardit-card-api"
CARDS_CLIENT_SECRET = "723aa789be33d3195416aa86e04dabff4d936dea4af0c0ea83788b8db2cadc07"
BASE_URL          = "http://167.172.49.177:8082"
E2E_TENANT_ID     = "00000000-0000-0000-0000-000000000001"
AFFILIATE_ID      = "a7d5929b-cba8-4e97-8985-2ce1d9fc91c3"

SIGNING_KEY_PEM = """-----BEGIN PRIVATE KEY-----
MIGHAgEAMBMGByqGSM49AgEGCCqGSM49AwEHBG0wawIBAQQguLTJ5EFCK3ayPpFj
C4vhlDXs0SFJELvhT754HsbHNGihRANCAAQCKqyhvvbCVHhPGHyuqip0fwemnQWs
IhkimdE3yKI8TNNQKqk7bNRSGWwXzKCMb7n2x7yZlCmRj9rU+VGylr//
-----END PRIVATE KEY-----"""

CANDIDATES = [
    "CAR-0189A4ABA51244F88AD081227F7B5567",
    "CAR-4060D0640BF344829D2BCCAC48CF1C93",
    "CAR-458988116F374475A207DD488DC450AD",
    "CAR-60B79E30E78546659E0C174EED568DBD",
    "CAR-726A48DE57F345EEB80FC1985A064059",
    "CAR-C6A21C0B89244670A92253471439E9D3",
]

def mint_token():
    for attempt in range(4):
        try:
            r = requests.post(
                IAM_URL,
                data={"grant_type": "client_credentials",
                      "client_id": CARDS_CLIENT_ID,
                      "client_secret": CARDS_CLIENT_SECRET},
                timeout=20,
            )
            if r.status_code == 200:
                d = r.json()
                token = d.get("access_token") or d.get("token") or d.get("accessToken")
                if token:
                    print(f"  token minted OK (attempt {attempt+1})")
                    return token
            print(f"  token attempt {attempt+1}: HTTP {r.status_code} — retrying...")
        except Exception as e:
            print(f"  token attempt {attempt+1} error: {e} — retrying...")
        time.sleep(4)
    raise RuntimeError("Could not mint token after 4 attempts")

def load_key():
    return serialization.load_pem_private_key(SIGNING_KEY_PEM.strip().encode(), password=None)

def sign_request(method, path, query_str, body_bytes, private_key):
    ts    = str(int(time.time()))
    nonce = uuid.uuid4().hex
    body_hash = hashlib.sha256(body_bytes).hexdigest()
    payload = "\n".join([method.upper(), path, query_str, ts, nonce, body_hash])
    sig_bytes = private_key.sign(payload.encode("utf-8"), ec.ECDSA(hashes.SHA256()))
    import base64
    sig = base64.b64encode(sig_bytes).decode()
    return sig, ts, nonce

def freeze(card_id, token, private_key):
    path = f"/api/v1/cards/{card_id}/freeze"
    body = {
        "requestContext": {
            "requestId":      str(uuid.uuid4()),
            "actorUserId":    "USR-AFF-20045",
            "userType":       "AFFILIATE",
            "tenantId":       E2E_TENANT_ID,
            "affiliateId":    AFFILIATE_ID,
            "idempotencyKey": str(uuid.uuid4()),
        },
        "reason": "CUSTOMER_REQUEST",
    }
    body_bytes = json.dumps(body, separators=(",", ":")).encode("utf-8")
    sig, ts, nonce = sign_request("POST", path, "", body_bytes, private_key)

    headers = {
        "Authorization":  f"Bearer {token}",
        "Content-Type":   "application/json",
        "Accept":         "application/json",
        "X-IAM-Signature": sig,
        "X-IAM-Timestamp": ts,
        "X-IAM-Nonce":     nonce,
    }
    r = requests.post(BASE_URL + path, data=body_bytes, headers=headers, timeout=20)
    return r.status_code, r.text[:300]

def main():
    target = sys.argv[1] if len(sys.argv) > 1 else CANDIDATES[0]
    print(f"Target card: {target}")

    print("Minting token...")
    token = mint_token()

    print("Loading signing key...")
    key = load_key()

    print(f"Sending freeze request...")
    status, body = freeze(target, token, key)
    print(f"  HTTP {status}")
    print(f"  Body: {body}")

    if status in (200, 201, 204):
        print(f"\nSUCCESS — {target} is now FROZEN. Re-run the E2E runner.")
    elif status == 409:
        print(f"\nCard already in a state that can't be frozen (409). Try a different card.")
    else:
        print(f"\nFailed. Try the next candidate or check the response above.")

if __name__ == "__main__":
    main()
