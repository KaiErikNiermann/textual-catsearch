"""The shared spec: the Python reference's answers, written out for the TypeScript port to match.

``ops`` is the one dispatcher both implementations provide (``js/test/harness/ops.ts`` is its
twin): a case names an operation and its arguments as JSON and gets a JSON answer back. The
golden fixtures under ``spec/fixtures`` are those answers for a fixed corpus; the differential
test asks both implementations the same generated cases and compares.
"""
