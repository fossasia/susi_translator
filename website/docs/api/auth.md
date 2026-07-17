---
sidebar_position: 6
---

# Authentication & Security

The Authentication API manages the Organizer lifecycle, secures all streaming/tenant endpoints, and issues JWT tokens via secure HTTP-Only cookies.

## Security Baseline

We enforce strict security rules at the infrastructure level.

1. **`JWT_SECRET_KEY` Validation**: The `_require_secret_key()` function runs on boot. If the secret key is missing, under 32 characters, or matches a known weak placeholder (e.g., `"change-me"`), the server intentionally crashes (`RuntimeError`). This prevents operators from deploying insecure instances.
2. **Cookie Security**:
   - `JWT_COOKIE_SECURE`: Enforces HTTPS-only transmission.
   - `JWT_COOKIE_SAMESITE`: Set to `Lax` to prevent most CSRF attacks.
   - `JWT_COOKIE_CSRF_PROTECT`: Implicitly enabled when HTTPS is active, requiring a `X-CSRF-TOKEN` header on modifying requests.
3. **Rate Limiting**: `Flask-Limiter` protects sensitive endpoints (like signup and login) to prevent brute-force credential stuffing.

---

## Endpoints

### 1. `POST /auth/api/signup`

Creates a new Organizer account.

**Payload**:

```json
{
  "email": "user@example.com",
  "password": "********",
  "name": "Jane Doe"
}
```

**Response (201 Created)**: Returns account details and sets the JWT access cookie.

### 2. `POST /auth/api/login`

Authenticates an existing Organizer.

**Payload**:

```json
{
  "email": "user@example.com",
  "password": "********"
}
```

**Response (200 OK)**: Returns account details, sets the JWT access cookie, and returns a CSRF token.

### 3. `POST /auth/api/logout`

Logs out the current Organizer.

**Response (200 OK)**: Unsets the JWT cookies and adds the JWT ID (`jti`) to the PostgreSQL `TokenBlocklist` table. We use a `@jwt.token_in_blocklist_loader` to verify this list on every request, preventing token replay attacks.

### 4. `GET /auth/api/me`

Fetches the currently authenticated Organizer's profile.

**Response (200 OK)**:

```json
{
  "status": "success",
  "organizer": {
    "id": 1,
    "email": "user@example.com",
    "name": "Jane Doe"
  }
}
```

### 5. `GET /auth/api/status`

Checks if the current session has a valid JWT token. Unlike `/me`, this endpoint does not require authentication; it simply returns `authenticated: false` if no valid token is present, which is useful for frontend routing guards.

### 6. `POST /internal/token-refresh` (Internal)

An internal API designed specifically for the `audio_grabber.py` subprocess.
Since the background audio grabber runs detached from the browser, it cannot rely on long-lived cookies. It uses a short-lived internal token (defined by `INTERNAL_TOKEN_EXPIRY_MINUTES`), and hits this endpoint proactively at 80% of the expiry window to mint a fresh token, ensuring uninterrupted streaming for hours.
