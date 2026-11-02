"""diff 解析、文件筛选与智能打包测试。"""
from review_tools.bundle import build_bundles
from review_tools.diff_utils import added_lines, parse_diff


SAMPLE_DIFF = """\
diff --git a/src/main/java/OrderService.java b/src/main/java/OrderService.java
index 111..222 100644
--- a/src/main/java/OrderService.java
+++ b/src/main/java/OrderService.java
@@ -10,3 +10,5 @@ public class OrderService {
     void before() {}
+    void after1() {}
+    void after2() {}
     void tail() {}
diff --git a/src/test/java/OrderServiceTest.java b/src/test/java/OrderServiceTest.java
new file mode 100644
--- /dev/null
+++ b/src/test/java/OrderServiceTest.java
@@ -0,0 +1,2 @@
+class OrderServiceTest {}
+// done
diff --git a/package-lock.json b/package-lock.json
index 333..444 100644
--- a/package-lock.json
+++ b/package-lock.json
@@ -1,1 +1,2 @@
+"locked": true
diff --git a/logo.png b/logo.png
index 555..666 100644
Binary files a/logo.png and b/logo.png differ
"""


def test_parse_diff_files_and_filtering():
    p = parse_diff(SAMPLE_DIFF)
    reviewed = [f["path"] for f in p["files"]]
    assert "src/main/java/OrderService.java" in reviewed
    assert "src/test/java/OrderServiceTest.java" in reviewed
    # 锁文件与二进制被过滤但保留统计
    filtered = [f["path"] for f in p["filtered"]]
    assert "package-lock.json" in filtered and "logo.png" in filtered
    assert p["stats"]["total"] == 4 and p["stats"]["reviewed"] == 2 and p["stats"]["filtered"] == 2


def test_line_numbers_map_to_new_file():
    p = parse_diff(SAMPLE_DIFF)
    svc = next(f for f in p["files"] if f["path"].endswith("OrderService.java"))
    adds = added_lines(svc)
    # hunk 从 +10 起：上下文 before(10) 之后新增两行为 11、12
    assert [a["line"] for a in adds] == [11, 12]
    assert adds[0]["text"] == "    void after1() {}"


def test_new_file_hunk_starts_at_one():
    p = parse_diff(SAMPLE_DIFF)
    tst = next(f for f in p["files"] if "Test" in f["path"])
    assert tst["is_new"]
    assert [a["line"] for a in added_lines(tst)] == [1, 2]


def test_empty_diff():
    p = parse_diff("")
    assert p["files"] == [] and p["stats"]["total"] == 0


def test_bundles_pair_impl_with_test():
    p = parse_diff(SAMPLE_DIFF)
    bundles = build_bundles(p["files"])
    assert len(bundles) >= 1
    paired = next((b for b in bundles if len(b["files"]) == 2), None)
    assert paired, "实现与测试应打包到同一评审单元"
    names = paired["files"]
    assert any("OrderService.java" in n for n in names) and any("Test" in n for n in names)


def test_bundles_size_cap():
    files = [{"path": f"src/mod{i}.py", "added_lines": 500, "hunks": [], "is_new": False, "is_binary": False} for i in range(6)]
    bundles = build_bundles(files)
    assert all(b["added_lines"] <= 1200 for b in bundles)
    assert all(len(b["files"]) <= 8 for b in bundles)
    assert sum(len(b["files"]) for b in bundles) == 6
