"""Services by typed key: a slice provides an adapter, routes get it, a test overrides it."""

import threading

import pytest

from app.services import Key, Services, override

GREETING = Key[str]("greeting")
COUNT = Key[int]("count")


def test_a_provided_service_is_built_once_on_first_use() -> None:
    built: list[str] = []
    services = Services()

    services.provide(GREETING, lambda: built.append("real") or "hello")

    assert built == []
    assert services.get(GREETING) == "hello"
    assert services.get(GREETING) == "hello"
    assert built == ["real"]


def test_an_override_wins_and_the_real_adapter_is_never_built() -> None:
    built: list[str] = []
    services = Services([override(GREETING, "fake")])

    services.provide(GREETING, lambda: built.append("real") or "hello")

    assert services.get(GREETING) == "fake"
    assert built == []


def test_an_override_is_available_without_a_provider() -> None:
    assert Services([override(COUNT, 3)]).get(COUNT) == 3


def test_an_unknown_service_is_named() -> None:
    with pytest.raises(LookupError, match="greeting"):
        Services().get(GREETING)


def test_find_returns_none_for_an_unknown_service() -> None:
    services = Services()
    services.provide(COUNT, lambda: 1)

    assert services.find(GREETING) is None
    assert services.find(COUNT) == 1


def test_two_providers_of_one_key_are_a_mistake() -> None:
    services = Services()
    services.provide(GREETING, lambda: "a")

    with pytest.raises(ValueError, match="greeting"):
        services.provide(GREETING, lambda: "b")


def test_overriding_one_key_twice_is_a_mistake() -> None:
    with pytest.raises(ValueError, match="greeting"):
        Services([override(GREETING, "a"), override(GREETING, "b")])


def test_concurrent_first_uses_build_once() -> None:
    built: list[int] = []
    barrier = threading.Barrier(8)
    services = Services()

    def build() -> int:
        built.append(1)
        return len(built)

    services.provide(COUNT, build)

    def use() -> None:
        barrier.wait()
        services.get(COUNT)

    threads = [threading.Thread(target=use) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert built == [1]


def test_a_builder_may_use_another_service() -> None:
    services = Services()
    services.provide(COUNT, lambda: 2)
    services.provide(GREETING, lambda: "hi" * services.get(COUNT))

    assert services.get(GREETING) == "hihi"
