# LLM 语义评审基准集（红队导出）

以下 diff 各含一个语义缺陷，用于 LLM 模式评审加压：模型应定位并给出 category/severity。

## B9-698（off_by_one）
```diff
diff --git a/o.py b/o.py
new file mode 100644
--- a/dev/null
+++ b/o.py
@@ -0,0 +1,2 @@
+for i in range(len(items)):
+    process(items[i + 1])
```

## B9-926（float_equality）
```diff
diff --git a/f.py b/f.py
new file mode 100644
--- a/dev/null
+++ b/f.py
@@ -0,0 +1,1 @@
+if total == 0.3: settle()
```

## B9-366（resource_leak）
```diff
diff --git a/r.py b/r.py
new file mode 100644
--- a/dev/null
+++ b/r.py
@@ -0,0 +1,2 @@
+f = open('x')
+data = f.read()
```

## B9-866（tz_naive）
```diff
diff --git a/t.py b/t.py
new file mode 100644
--- a/dev/null
+++ b/t.py
@@ -0,0 +1,1 @@
+ts = datetime.now()
```

## B9-670（unbounded_retry）
```diff
diff --git a/u.py b/u.py
new file mode 100644
--- a/dev/null
+++ b/u.py
@@ -0,0 +1,3 @@
+while True:
+    try: fetch(); break
+    except: continue
```

## B9-698（off_by_one）
```diff
diff --git a/o.py b/o.py
new file mode 100644
--- a/dev/null
+++ b/o.py
@@ -0,0 +1,2 @@
+for i in range(len(items)):
+    process(items[i + 1])
```

## B9-926（float_equality）
```diff
diff --git a/f.py b/f.py
new file mode 100644
--- a/dev/null
+++ b/f.py
@@ -0,0 +1,1 @@
+if total == 0.3: settle()
```

## B9-366（resource_leak）
```diff
diff --git a/r.py b/r.py
new file mode 100644
--- a/dev/null
+++ b/r.py
@@ -0,0 +1,2 @@
+f = open('x')
+data = f.read()
```

## B9-866（tz_naive）
```diff
diff --git a/t.py b/t.py
new file mode 100644
--- a/dev/null
+++ b/t.py
@@ -0,0 +1,1 @@
+ts = datetime.now()
```

## B9-670（unbounded_retry）
```diff
diff --git a/u.py b/u.py
new file mode 100644
--- a/dev/null
+++ b/u.py
@@ -0,0 +1,3 @@
+while True:
+    try: fetch(); break
+    except: continue
```

## B10-035（concurrency_check_act）
```diff
diff --git a/c.java b/c.java
new file mode 100644
--- a/dev/null
+++ b/c.java
@@ -0,0 +1,1 @@
+if (count > 0) { decrement(); }
```

## B10-788（sql_injection_concat）
```diff
diff --git a/s.py b/s.py
new file mode 100644
--- a/dev/null
+++ b/s.py
@@ -0,0 +1,1 @@
+cursor.execute("SELECT * FROM t WHERE id = " + user_id)
```

## B10-695（silent_partial_write）
```diff
diff --git a/w.py b/w.py
new file mode 100644
--- a/dev/null
+++ b/w.py
@@ -0,0 +1,2 @@
+for row in rows:
+    sink.write(row)
```

## B10-233（cache_stampede）
```diff
diff --git a/ch.py b/ch.py
new file mode 100644
--- a/dev/null
+++ b/ch.py
@@ -0,0 +1,5 @@
+def get(k):
+    v = cache.get(k)
+    if v is None:
+        v = db_load(k); cache.set(k, v)
+    return v
```
