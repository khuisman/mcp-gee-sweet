# Lists: nesting widths x type combinations

Each case: three levels deep, then an item back at level 1, then an item back at
level 0, so numbering continuation after a nested block is checked at both levels.
Level 2 uses the same list type as level 0.

### LN-01 — bullet in bullet, 2sp

- Top one
  - Child one
    - Grandchild one
    - Grandchild two
  - Child two
- Top two
- Top three

### LN-02 — bullet in numbered, 2sp

1. Top one
  - Child one
    1. Grandchild one
    2. Grandchild two
  - Child two
2. Top two
3. Top three

### LN-03 — numbered in bullet, 2sp

- Top one
  1. Child one
    - Grandchild one
    - Grandchild two
  2. Child two
- Top two
- Top three

### LN-04 — numbered in numbered, 2sp

1. Top one
  1. Child one
    1. Grandchild one
    2. Grandchild two
  2. Child two
2. Top two
3. Top three

### LN-05 — bullet in bullet, 3sp

- Top one
   - Child one
      - Grandchild one
      - Grandchild two
   - Child two
- Top two
- Top three

### LN-06 — bullet in numbered, 3sp

1. Top one
   - Child one
      1. Grandchild one
      2. Grandchild two
   - Child two
2. Top two
3. Top three

### LN-07 — numbered in bullet, 3sp

- Top one
   1. Child one
      - Grandchild one
      - Grandchild two
   2. Child two
- Top two
- Top three

### LN-08 — numbered in numbered, 3sp

1. Top one
   1. Child one
      1. Grandchild one
      2. Grandchild two
   2. Child two
2. Top two
3. Top three

### LN-09 — bullet in bullet, 4sp

- Top one
    - Child one
        - Grandchild one
        - Grandchild two
    - Child two
- Top two
- Top three

### LN-10 — bullet in numbered, 4sp

1. Top one
    - Child one
        1. Grandchild one
        2. Grandchild two
    - Child two
2. Top two
3. Top three

### LN-11 — numbered in bullet, 4sp

- Top one
    1. Child one
        - Grandchild one
        - Grandchild two
    2. Child two
- Top two
- Top three

### LN-12 — numbered in numbered, 4sp

1. Top one
    1. Child one
        1. Grandchild one
        2. Grandchild two
    2. Child two
2. Top two
3. Top three

### LN-13 — bullet in bullet, tab

- Top one
	- Child one
		- Grandchild one
		- Grandchild two
	- Child two
- Top two
- Top three

### LN-14 — bullet in numbered, tab

1. Top one
	- Child one
		1. Grandchild one
		2. Grandchild two
	- Child two
2. Top two
3. Top three

### LN-15 — numbered in bullet, tab

- Top one
	1. Child one
		- Grandchild one
		- Grandchild two
	2. Child two
- Top two
- Top three

### LN-16 — numbered in numbered, tab

1. Top one
	1. Child one
		1. Grandchild one
		2. Grandchild two
	2. Child two
2. Top two
3. Top three
