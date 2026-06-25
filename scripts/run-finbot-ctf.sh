# Run this script inside the provisioned sandbox.
git clone https://github.com/redis/redis.git --branch 6.2.14 --depth 1
cd redis/
make -j4
cp src/redis-server /sandbox/redis-server
cp src/redis-cli /sandbox/redis-cli
/sandbox/redis-server --daemonize yes --port 6379 --bind 127.0.0.1 --save "" --appendonly no
/sandbox/redis-cli ping
cd ..
uv run --python $(which python3) python scripts/db.py setup
/sandbox/redis-cli XADD finbot:events:business '*' init true
/sandbox/redis-cli XGROUP CREATE finbot:events:business ctf-processor 0 MKSTREAM
uv run --python $(which python3) python run.py 
