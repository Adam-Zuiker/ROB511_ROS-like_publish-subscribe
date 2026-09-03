.PHONY: build run map clean
build:
	python3 -m compileall -q src
run:
	python3 src/main.py
map:
	@test -f maps/student_map.json || { echo "Create your own maps/student_map.json first; see maps/README.md" >&2; exit 1; }
	python3 tools/map_to_rosbridge.py maps/student_map.json
clean:
	find src tests -name '__pycache__' -type d -exec rm -rf {} +
