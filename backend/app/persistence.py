import json
import secrets
from contextlib import asynccontextmanager

from fastapi import HTTPException


class Lease:
    def __init__(self, repository, name, token):
        self.repository = repository
        self.name = name
        self.token = token

    async def renew(self):
        renewed = await self.repository.redis.eval(
            "if redis.call('GET', KEYS[1]) == ARGV[1] then return redis.call('EXPIRE', KEYS[1], 60) end return 0",
            keys=[self.repository.key(self.name)],
            args=[self.token],
        )
        if not renewed:
            raise HTTPException(
                409,
                "Operation interrupted. Review the saved results before any new batch.",
            )

    async def save(self, name, value, ttl):
        saved = await self.repository.redis.eval(
            "if redis.call('GET', KEYS[1]) ~= ARGV[1] then return 0 end redis.call('SET', KEYS[2], ARGV[2], 'EX', ARGV[3]) return 1",
            keys=[self.repository.key(self.name), self.repository.key(name)],
            args=[self.token, json.dumps(value), ttl],
        )
        if not saved:
            raise HTTPException(
                409,
                "Operation interrupted. Review the saved results before any new batch.",
            )


class Repository:
    def __init__(self, redis, namespace="kuts-production"):
        self.redis = redis
        self.namespace = namespace

    def key(self, name):
        return f"{self.namespace}:{name}"

    async def get(self, name):
        value = await self.redis.get(self.key(name))
        return json.loads(value) if value is not None else None

    async def put(self, name, value, ttl):
        await self.redis.set(self.key(name), json.dumps(value), ex=ttl)

    async def take(self, name):
        value = await self.redis.eval(
            "local value = redis.call('GET', KEYS[1]) redis.call('DEL', KEYS[1]) return value",
            keys=[self.key(name)],
            args=[],
        )
        return json.loads(value) if value else None

    async def limited(self, name, maximum, seconds=60):
        count = await self.redis.eval(
            "local count = redis.call('INCR', KEYS[1]) if count == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end return count",
            keys=[self.key(f"rate:{name}")],
            args=[seconds],
        )
        if int(count) > maximum:
            raise HTTPException(
                429,
                "Too many requests. Wait one minute.",
                headers={"Retry-After": str(seconds)},
            )

    @asynccontextmanager
    async def lock(self, name):
        token = secrets.token_urlsafe(24)
        name = f"lock:{name}"
        acquired = await self.redis.set(self.key(name), token, nx=True, ex=60)
        if not acquired:
            raise HTTPException(
                409, "Another organiser operation is running. Please wait."
            )
        try:
            yield Lease(self, name, token)
        finally:
            await self.redis.eval(
                "if redis.call('GET', KEYS[1]) == ARGV[1] then return redis.call('DEL', KEYS[1]) end return 0",
                keys=[self.key(name)],
                args=[token],
            )
