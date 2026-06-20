# Manager exposure context contract

This contract defines the fields Manager sends to the external gate before a new order is allowed.

## Fields

- `current_symbol_exposure`: filled position exposure for the target symbol only.
- `current_total_exposure`: filled portfolio exposure only. Do not include pending, placed, or partially-filled orders here.
- `open_orders_exposure`: outstanding exposure from pending, placed, and partially-filled orders.
- `requested_quantity`: desired quantity for the new order being reviewed. It is not the current position size.

## Projected exposure owner

The external gate owns the projected exposure calculation:

```text
projected_total_exposure = current_total_exposure + open_orders_exposure + new_order_value
```

Manager must keep filled exposure and outstanding order exposure separate so downstream checks do not double-count the same value.

## Manager defaults

When a caller does not provide `requested_quantity`, Manager derives a conservative quantity from:

- portfolio value
- risk per trade
- max position percent
- entry price
- protection price

For sell/exit decisions, Manager may use the existing position size as the desired exit quantity.
