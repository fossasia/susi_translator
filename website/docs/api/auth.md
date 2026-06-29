---
sidebar_position: 6
---

# Authentication

The Authentication API manages the Organizer lifecycle and issues JWT tokens via secure HTTP-Only cookies.

## Why JWT in Cookies?

Using HTTP-Only cookies for JWT prevents Cross-Site Scripting (XSS) attacks from accessing the tokens, providing a much higher security baseline compared to storing tokens in `localStorage`.

All endpoints except `signup`, `login`, and `status` require the JWT token to be present.

---

## Endpoints

### 1. `POST /auth/api/signup`

Creates a new Organizer account.

**Payload**:

```json
{
  "email": "user@example.com",
  "password": "securepassword",
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
  "password": "securepassword"
}
```

**Response (200 OK)**: Returns account details and sets the JWT access cookie.

### 3. `POST /auth/api/logout`

Logs out the current Organizer.

**Response (200 OK)**: Unsets the JWT cookies and adds the JWT ID (`jti`) to the database blocklist to prevent token reuse (replay attacks).

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
