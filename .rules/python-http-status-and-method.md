# HTTP Status Codes and Methods

> Use the Python standard library `http.HTTPStatus` and
> `http.HTTPMethod` enums throughout. Never use magic numbers or
> framework-specific constants (e.g. `falcon.HTTP_200`) for HTTP
> status codes or methods.

## `http.HTTPStatus`

`http.HTTPStatus` is an `IntEnum` whose members compare equal to their
integer values. Use it everywhere an HTTP status code appears:
response status assignment, threshold comparisons, test assertions,
and error construction.

```python
from http import HTTPStatus

# Setting a response status (works with Falcon, Starlette, etc.)
resp.status = HTTPStatus.OK

# Threshold comparisons
if response.status_code >= HTTPStatus.BAD_REQUEST:
    raise APIError(response.status_code)

# Named constants for specific codes
if response.status_code == HTTPStatus.TOO_MANY_REQUESTS:
    back_off(response)

# Test assertions — prefer status_code (int) over status (str)
assert result.status_code == HTTPStatus.NOT_FOUND
```

### Why

- **Self-documenting:** `HTTPStatus.NOT_FOUND` is clearer than `404`
  or `falcon.HTTP_404`.
- **Framework-agnostic:** the enum is part of the stdlib and works
  with any HTTP library or framework.
- **Type-safe:** static analysers can verify exhaustive `match`/`case`
  branches over `HTTPStatus` members.

## `http.HTTPMethod`

`http.HTTPMethod` is a `StrEnum` whose members compare equal to their
string values (`HTTPMethod.GET == "GET"`). Use it whenever an HTTP
method appears as a literal string — for example, in client calls,
routing tables, or test fixtures.

```python
from http import HTTPMethod

# Client calls
response = await client.request(HTTPMethod.POST, url, json=payload)

# Comparisons
if request.method == HTTPMethod.GET:
    ...
```

### Why

- **Discoverable:** IDE autocompletion lists valid methods.
- **Typo-proof:** `HTTPMethod.DLETE` is a compile-time error;
  `"DLETE"` is not.

## Banned alternatives

| Do not use | Use instead |
|---|---|
| `falcon.HTTP_200`, `falcon.HTTP_404`, … | `HTTPStatus.OK`, `HTTPStatus.NOT_FOUND`, … |
| `200`, `404`, `500` (bare integers) | `HTTPStatus.OK`, `HTTPStatus.NOT_FOUND`, `HTTPStatus.INTERNAL_SERVER_ERROR` |
| `"GET"`, `"POST"`, … (bare strings) | `HTTPMethod.GET`, `HTTPMethod.POST`, … |

______________________________________________________________________

These conventions keep HTTP semantics explicit, framework-independent,
and verifiable by static analysis.
