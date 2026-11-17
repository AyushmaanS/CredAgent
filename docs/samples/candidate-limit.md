# Candidate-limit measurement (design §11a)

Date 2026-11-17 · real Jev · repeats 3 · served: jev-1.14.0

| limit | order | calls | target offered | correct (when offered) | said none (when offered) | median ms | p90 ms | mean request chars |
|---|---|---|---|---|---|---|---|---|
| 20 | ranked | 27 | 89 % | 100 % | 0 % | 304 | 402 | 4817 |
| 20 | target_first | 27 | 100 % | 100 % | 0 % | 322 | 414 | 4816 |
| 20 | target_last | 27 | 100 % | 100 % | 0 % | 345 | 405 | 4816 |
| 40 | ranked | 27 | 100 % | 89 % | 11 % | 310 | 380 | 6018 |
| 40 | target_first | 27 | 100 % | 100 % | 0 % | 342 | 446 | 6018 |
| 40 | target_last | 27 | 100 % | 96 % | 4 % | 315 | 418 | 6018 |
| 60 | ranked | 27 | 100 % | 89 % | 11 % | 320 | 403 | 6765 |
| 60 | target_first | 27 | 100 % | 100 % | 0 % | 338 | 409 | 6765 |
| 60 | target_last | 27 | 100 % | 96 % | 4 % | 306 | 384 | 6765 |

Per page (ranked order): target rank on the page and candidates on the page

- case 0 (app, not quoted): target ranked #1 of 50 page candidates
- case 1 (app, not quoted): target ranked #37 of 50 page candidates
- case 2 (oauth2, quoted): target ranked #1 of 54 page candidates
- case 3 (oauth2, quoted): target ranked #1 of 54 page candidates
- case 4 (oauth2, not quoted): target ranked #1 of 54 page candidates
- case 5 (list, not quoted): target ranked #1 of 19 page candidates
- case 6 (list, quoted): target ranked #1 of 19 page candidates
- case 7 (form, not quoted): target ranked #1 of 11 page candidates
- case 8 (home, not quoted): target ranked #1 of 7 page candidates
