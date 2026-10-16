# oracle-mutants: oracle-mutants/word-count-weak

- Reference solution reward (Harbor oracle run): **1.0**
- Same artifacts re-verified by oracle-mutants: **1.0**
- Mutants run: **10** — rejected 2, accepted **8**, no reward (crash/timeout) 0
- Accepted by severity: strong 1, medium 7, weak 0

## Accepted strong mutants — likely verifier gap

### `/app/counts.json` — numbers-to-zero

set all 9 numeric values to 0

```diff
--- reference
+++ mutant
@@ -1,11 +1,11 @@
 {
-  "a": 2,
-  "and": 1,
-  "cat": 2,
-  "dog": 2,
-  "log": 1,
-  "mat": 1,
-  "on": 2,
-  "sat": 2,
-  "the": 4
+  "a": 0,
+  "and": 0,
+  "cat": 0,
+  "dog": 0,
+  "log": 0,
+  "mat": 0,
+  "on": 0,
+  "sat": 0,
+  "the": 0
 }
```

## Accepted medium mutants — worth a look

### `/app/counts.json` — drop-key

removed top-level key 'a'

```diff
--- reference
+++ mutant
@@ -1,3 +1,2 @@
 {
-  "a": 2,
   "and": 1,
```

### `/app/counts.json` — drop-key

removed top-level key 'and'

```diff
--- reference
+++ mutant
@@ -2,3 +2,2 @@
   "a": 2,
-  "and": 1,
   "cat": 2,
```

### `/app/counts.json` — drop-key

removed top-level key 'cat'

```diff
--- reference
+++ mutant
@@ -3,3 +3,2 @@
   "and": 1,
-  "cat": 2,
   "dog": 2,
```

### `/app/counts.json` — drop-key

removed top-level key 'dog'

```diff
--- reference
+++ mutant
@@ -4,3 +4,2 @@
   "cat": 2,
-  "dog": 2,
   "log": 1,
```

### `/app/counts.json` — drop-key

removed top-level key 'log'

```diff
--- reference
+++ mutant
@@ -5,3 +5,2 @@
   "dog": 2,
-  "log": 1,
   "mat": 1,
```

### `/app/counts.json` — nudge-number

['a']: 2 -> 3

Tolerance probe: accepted every step up to +1000: this value looks unchecked.

```diff
--- reference
+++ mutant
@@ -1,3 +1,3 @@
 {
-  "a": 2,
+  "a": 3,
   "and": 1,
```

### `/app/counts.json` — nullify

['a']: 2 -> null

```diff
--- reference
+++ mutant
@@ -1,3 +1,3 @@
 {
-  "a": 2,
+  "a": null,
   "and": 1,
```


_A mutant is **accepted** when the verifier still awards full reward. Strong mutants are almost never correct answers; medium and weak ones need a human to judge whether the task allows them._
