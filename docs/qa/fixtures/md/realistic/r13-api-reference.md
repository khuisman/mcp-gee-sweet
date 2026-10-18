# Orders API Reference

Base URL: `https://api.example.com/v2`

All requests need an `Authorization: Bearer <token>` header.

## List orders

`GET /orders`

Returns orders for the authenticated account, newest first.

### Query parameters

| Name | Type | Required | Description |
|------|------|:--------:|-------------|
| `status` | string | No | One of `pending`, `paid`, `shipped`, `cancelled` |
| `limit` | integer | No | 1–100, default `20` |
| `cursor` | string | No | Pagination cursor from a previous response |

### Example

```bash
curl -H "Authorization: Bearer $TOKEN" \
  "https://api.example.com/v2/orders?status=paid&limit=2"
```

```json
{
  "data": [
    {"id": "ord_123", "status": "paid", "total": 4200},
    {"id": "ord_124", "status": "paid", "total": 1999}
  ],
  "next_cursor": "eyJpZCI6Im9yZF8xMjQifQ"
}
```

## Create an order

`POST /orders`

### Body

- `items` (array, required): each item has:
  - `sku` (string)
  - `quantity` (integer, ≥ 1)
- `shipping_address` (object, required)
- `coupon` (string, optional)

### Errors

| Code | Meaning |
|------|---------|
| `400` | Validation failed; see `errors[]` |
| `402` | Payment required |
| `409` | Duplicate `Idempotency-Key` |
| `429` | Rate limited; retry after the `Retry-After` header |

> **Idempotency:** send an `Idempotency-Key` header on every `POST`. Retrying with
> the same key returns the original response instead of creating a second order.

## Changelog

- **2026-09-01:** added `cursor` pagination; `page` is deprecated
- **2026-06-15:** `total` is now in minor units (cents)
