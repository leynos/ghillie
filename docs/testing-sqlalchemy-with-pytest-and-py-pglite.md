# Testing SQLAlchemy 2.x with Postgres: PyTest and **py-pglite** Guide

## Why Use **py-pglite** for SQLAlchemy Tests

Testing a PostgreSQL-backed application can be slow or complex if you need to
spin up real databases or containers. **py-pglite** offers an embeddable
Postgres for Python tests – essentially a **real PostgreSQL database running
in-memory** – with **zero config**. This means you can run tests **just like
using SQLite**, but get all Postgres features (JSONB, array types, extensions,
etc.) in your
tests([1](https://github.com/wey-gu/py-pglite#:~:text=%2A%20Zero%20config%20,SQLAlchemy%2C%20Django%2C%20psycopg%2C%20asyncpg)).
 With **py-pglite**, each test can have a **fresh, isolated database** that is
created and destroyed automatically, ensuring no state leaks between
tests([2](https://void.abn.is/a-python-project-postgresql-and-wasm/#:~:text=The%20,also%20provides%20fixtures%20for%20Django)).
 In short, it provides:

- **Real Postgres in tests:** You’re testing against a true Postgres engine
  (not an SQLite or mock), so you can use Postgres-specific features and catch
  issues
  early([2](https://void.abn.is/a-python-project-postgresql-and-wasm/#:~:text=,containers%20for%20every%20test%20run)).

- **Ephemeral & isolated:** By default, each test gets its own clean database,
  preventing flaky tests caused by leftover
  data([2](https://void.abn.is/a-python-project-postgresql-and-wasm/#:~:text=The%20,also%20provides%20fixtures%20for%20Django)).

- **Fast startup:** No Docker or external service needed – py-pglite
  initializes in a couple of seconds vs. tens of seconds for a
  container([1](https://github.com/wey-gu/py-pglite#:~:text=%2A%20Zero%20config%20,SQLAlchemy%2C%20Django%2C%20psycopg%2C%20asyncpg)).

- **Minimal boilerplate:** PyTest fixtures are provided to set up and tear down
  the DB automatically, removing manual setup/cleanup
  scripts([2](https://void.abn.is/a-python-project-postgresql-and-wasm/#:~:text=engine%20like%20SQLite,and%20tearing%20down%20test%20databases)).

**py-pglite** achieves this by running a WebAssembly-based Postgres engine
under the hood (PGlite) inside a Node.js
runtime([2](https://void.abn.is/a-python-project-postgresql-and-wasm/#:~:text=1,using%20it%20with)).
 (You’ll need Node.js 18+ installed, as the first run will fetch the PGlite
WASM package.) Once installed with `pip install py-pglite[sqlalchemy]`, it
integrates with PyTest to make database testing almost seamless.

## Setting Up **py-pglite** Fixtures in PyTest

After installing, **py-pglite** provides out-of-the-box PyTest fixtures for
SQLAlchemy. The most important are:

- **`pglite_engine`** – a SQLAlchemy Engine connected to a temporary Postgres
  instance (typically one per test).

- **`pglite_session`** – a SQLAlchemy ORM Session bound to the above engine.

These fixtures can be requested in your tests. **You don’t need to configure a
database URL or start a server manually** – simply including the fixture will
trigger py-pglite to launch an in-memory Postgres and yield a connection. For
example, a basic test might look like:

```python
# models.py – define an example model
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    email: Mapped[str]
```

```python
# test_models.py
from sqlalchemy import select


def test_user_creation(pglite_session):
    # Ensure the test database has the schema (e.g., run migrations or create tables)
    Base.metadata.create_all(pglite_session.bind)  # Using Base from our models

    # Use the session fixture just like a normal Session
    new_user = User(name="Alice", email="[email protected]")
    pglite_session.add(new_user)
    pglite_session.commit()

    # Query back the data to verify
    result = pglite_session.execute(select(User).where(User.name == "Alice"))
    user = result.scalar_one()

    assert user.email == "[email protected]"
    assert user.id is not None
```

When this test runs, `pglite_session` provides a **fully configured Session**
connected to a temporary Postgres. **The database instance is started just for
this test and torn down after**, so the next test starts with a clean
slate([2](https://void.abn.is/a-python-project-postgresql-and-wasm/#:~:text=The%20,also%20provides%20fixtures%20for%20Django)).
 You can interact with `pglite_session` exactly as you would with a normal
SQLAlchemy session to add/query objects. In this example we call
`Base.metadata.create_all(...)` to create the tables for our model in the
ephemeral database. In a real project, you’d typically run your Alembic
migrations to set up the schema (more on this below), but using `create_all` is
fine for simple cases.

**Note:** The first time you run a py-pglite test, it may take a moment to
download the WASM Postgres bundle via Node.js. After that, database startup is
very fast (a couple seconds or less) for each test.

## Writing Asynchronous Tests with SQLAlchemy 2.x and **pytest-asyncio**

SQLAlchemy 2.x supports an async ORM API, and you can test async database logic
with py-pglite as well. Py-pglite doesn’t yet provide a ready-made
`AsyncSession` fixture, but you can integrate it with a bit of setup. The key
steps are:

- **Enable async driver:** Install py-pglite with the async extra
  (`pip install py-pglite[asyncpg]`) so that the asyncpg driver is available.
  Py-pglite’s default engine uses the Psycopg driver via a Unix socket, which
  doesn’t directly work with SQLAlchemy’s `AsyncEngine`. Instead, we’ll run the
  Postgres in TCP mode and use `asyncpg`.

- **Get connection info:** Use a PGlite manager to obtain the host, port, and
  database name of the running instance. For example, if you request the
  `pglite_manager` fixture (which yields a `PGliteManager`), you can get an
  engine or DSN from it.

- **Create an AsyncEngine:** Build a SQLAlchemy AsyncEngine using
  `create_async_engine()` with the `asyncpg` driver pointing to the PGlite
  host/port. For example:
  `create_async_engine(f"postgresql+asyncpg://{host}:{port}/{database}")`
  ([1](https://github.com/wey-gu/py-pglite#:~:text=,engine%20%3D%20create_async_engine%28f%22postgresql%2Basyncpg%3A%2F%2F%7Bhost%7D%3A%7Bport%7D%2F%7Bdatabase)).

- **Use `pytest-asyncio`** to write async test functions that await database
  operations.

Below is an illustrative async test setup:

```python
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine


@pytest.mark.asyncio
async def test_async_insert_and_query():
    # Start a PGlite instance manually and get connection details
    from py_pglite import PGliteConfig, PGliteManager

    config = PGliteConfig(tcp_port=54321, tcp_host="127.0.0.1")  # use TCP mode on a free port
    async with PGliteManager(config) as pg_manager:  # start the Postgres WASM instance
        # Build an AsyncEngine using asyncpg driver
        pg_url = f"postgresql+asyncpg://postgres:postgres@{config.tcp_host}:{config.tcp_port}/postgres"
        async_engine = create_async_engine(pg_url, future=True)
        async with async_engine.begin() as conn:
            # (Optionally, run Alembic migrations here or create tables)
            await conn.run_sync(Base.metadata.create_all)
        # Use an AsyncSession to interact with the DB
        async with AsyncSession(async_engine) as session:
            new_item = User(name="Bob", email="[email protected]")
            session.add(new_item)
            await session.commit()
            # Query using SQLAlchemy's async API
            result = await session.execute(select(User).where(User.name == "Bob"))
            bob = result.scalar_one()
            assert bob.email == "[email protected]"
        # Dispose engine (closing all connections)
        await async_engine.dispose()
```

In this example we manually manage the PGlite lifecycle with `PGliteManager`
(which can be used as an async context manager). We configure it to listen on a
TCP port, then create an AsyncEngine to connect via `asyncpg`. We run
`Base.metadata.create_all` inside an `engine.begin()` block to create tables
(again, in real usage you might invoke migrations). Finally, we perform async
session operations (`await session.commit()`, `await session.execute(...)`) and
assertions.

**Key points for async usage:**

- Ensure the **driver and connection string** are correct. The DSN must use
  `postgresql+asyncpg://` (or an async psycopg DSN if using psycopg3’s async
  support). Py-pglite’s built-in connection string is hard-coded for
  psycopg+Unix socket by
  default([2](https://void.abn.is/a-python-project-postgresql-and-wasm/#:~:text=2,in%20your%20dependency%20tree))([2](https://void.abn.is/a-python-project-postgresql-and-wasm/#:~:text=,5432%20connection_string%20%3D)),
   so switching to TCP as shown above is the easiest path for async.

- **Use `pytest.mark.asyncio`** (from `pytest-asyncio`) on your async test
  functions so PyTest handles the event loop.

- The rest of the async test flows naturally – you can mix `asyncio` awaits
  with database calls as shown.

## Resetting the Database Between Tests (Function vs. Session Scope)

One of the advantages of py-pglite is test **isolation** – each test starts
with a blank database. By default, the provided `pglite_session` fixture has
**function scope**, meaning **each test function gets its own fresh
database**([1](https://github.com/wey-gu/py-pglite#:~:text=%2A%20Zero%20config%20,SQLAlchemy%2C%20Django%2C%20psycopg%2C%20asyncpg)).
 This is the safest approach to avoid cross-test interference. However, you
have flexibility in how to manage database scope and reset behavior:

- **Per test (function-scope)** – **Default**. Every test uses a new ephemeral
  Postgres instance. Migrations or table creation can run at the start of each
  test. This guarantees isolation but has the overhead of repeated startup and
  schema setup. Use this when tests need complete independence or if the
  database setup is lightweight.

- **Per test module or session (module/session-scope)** – A single database
  instance is shared by multiple tests, typically created at the beginning of
  the test run. You would run migrations **once per session** (not for each
  test) for
  speed([3](https://hoop.dev/blog/the-simplest-way-to-make-postgresql-pytest-work-like-it-should/#:~:text=How%20do%20you%20connect%20PostgreSQL,performance%20while%20avoiding%20database%20bloat)).
   This can significantly speed up a large test suite by avoiding redundant DB
  initialization. **However**, you must ensure isolation *within* that shared
  database. Common strategies include:

- **Truncate or clean tables between tests:** After each test, delete the data
  that was added. Py-pglite provides a utility
  `utils.clean_database_data(engine)` to wipe all tables (with an option to
  exclude certain
  tables)([4](https://www.xugj520.cn/archives/py-pglite-postgresql-testing-guide.html#:~:text=%E6%B8%85%E7%A9%BA%E6%95%B0%E6%8D%AE%E5%BA%93%E6%95%B0%E6%8D%AE)).
   You might call this in a function-scoped fixture that runs after each test
  if using a shared engine. Likewise, `utils.reset_sequences(engine)` will
  reset serial primary key counters so IDs start from 1
  again([4](https://www.xugj520.cn/archives/py-pglite-postgresql-testing-guide.html#:~:text=%E9%87%8D%E7%BD%AE%E8%87%AA%E5%A2%9E%E4%B8%BB%E9%94%AE%E5%BA%8F%E5%88%97))
   – useful for consistency in tests. These utilities help keep a
  session-scoped database *logically* fresh between tests.

- **Use savepoint rollbacks or transactions:** Another approach is to run each
  test inside a transaction and roll it back at the end, so no changes persist.
  For example, open a transaction in a setup fixture, yield the session to the
  test, and roll back in teardown. This works best if your code under test
  doesn’t itself manage transactions. (Note: When using SQLAlchemy’s Session,
  you might need to expire the session after rollback to prevent seeing stale
  state.)

- **Use separate schemas per test:** Py-pglite’s utilities can create/drop
  schemas if you prefer isolating data by
  schema([4](https://www.xugj520.cn/archives/py-pglite-postgresql-testing-guide.html#:~:text=Schema%20%E7%AE%A1%E7%90%86)).
   For instance, each test could operate in a schema named after the test
  function, and you drop it afterwards. This avoids messing with the entire DB
  and is useful in multi-tenant style testing.

Choosing the scope often involves a **trade-off between performance and
isolation**. If your test suite is small or you prioritize deterministic
isolation, function-scoped (fresh DB each test) is simplest. For large suites
where the DB setup is a bottleneck, consider a session-scoped database with
careful cleaning. As a rule of thumb: **apply schema migrations once per test
session and reuse the database for speed, but ensure each test starts from a
known empty
state**([3](https://hoop.dev/blog/the-simplest-way-to-make-postgresql-pytest-work-like-it-should/#:~:text=How%20do%20you%20connect%20PostgreSQL,performance%20while%20avoiding%20database%20bloat))([3](https://hoop.dev/blog/the-simplest-way-to-make-postgresql-pytest-work-like-it-should/#:~:text=Why%20does%20PostgreSQL%20PyTest%20improve,and%20hours%20from%20every%20week)).

## Applying Alembic Migrations in Tests

When using SQLAlchemy with Alembic for migrations, it’s best to apply those
migrations to your test database so that your schema in tests matches your
production schema. **Never assume your ORM models alone define the database
structure** – always account for migrations (which may include critical DDL
like constraints, indexes, etc.). Here’s how you can integrate Alembic into
your test setup:

- **Run migrations at setup:** Use a PyTest fixture (often session-scoped) to
  run `alembic upgrade head` against the test database. For example, you can
  load your Alembic `Config` and call `alembic.command.upgrade(config, "head")`
  once the py-pglite engine is up. If using `pglite_engine` fixture, you might
  write another fixture that depends on it:

```python
import alembic
from alembic.config import Config


@pytest.fixture(scope="session")
def migrated_engine(pglite_engine):
    # Point Alembic to the test DB URL
    alembic_cfg = Config("alembic.ini")
    alembic_cfg.set_main_option("sqlalchemy.url", str(pglite_engine.url))
    alembic.command.upgrade(alembic_cfg, "head")
    yield pglite_engine
    # (Optionally, downgrade or clean after tests)
```

Then use `migrated_engine` in tests instead of `pglite_engine` to ensure schema
is ready. This runs migrations once for the session. (If you insist on a fresh
DB per test function, you could run migrations in a function fixture, but that
is slower. It's usually unnecessary to re-run DDL for each test once the schema
is in
place([3](https://hoop.dev/blog/the-simplest-way-to-make-postgresql-pytest-work-like-it-should/#:~:text=How%20do%20you%20connect%20PostgreSQL,performance%20while%20avoiding%20database%20bloat)).)

- **Use `pytest-alembic` (optional):** The community has a plugin
  **pytest-alembic** that can automate applying migrations in tests and even
  has built-in tests for migration consistency. If you install it, you can
  configure it to run migrations in a fixture and validate that migrations
  produce the intended schema. This can be overkill for basic needs, but it’s
  worth knowing if you want to test the migrations themselves.

- **Teardown (if needed):** For a session-scoped DB, you might drop the
  database or roll back migrations after the tests. With py-pglite, however,
  the entire database is in memory and will vanish once the process ends. So
  explicit teardown of the schema is usually not required – simply let
  py-pglite shut down. If you created any persistent artifacts (like a files on
  disk via `work_dir` config), clean them up, but by default py-pglite is
  ephemeral.

By using Alembic in tests, you ensure your ORM code is always exercised against
the **actual database structure** as defined by your migrations. This catches
issues like missing migrations or mismatches between models and DB (a common
source of bugs) early in development. It also means if your migrations add seed
data or required setup, your tests can take advantage of that.

## Injecting Test Database into Your Application (Dependency Injection)

In many applications, especially web frameworks like **FastAPI** or **Flask**,
database access is provided via some form of *dependency injection* or global
session. For example, FastAPI might have a `get_db()` dependency that yields a
session, or you might have a module-level `SessionLocal()` for the app. When
testing, you want to **override those to use the py-pglite test database**
instead of your real database. Here’s how you can do that:

- **FastAPI dependency override:** If using FastAPI, you can override the
  `get_db` dependency in tests. Suppose your FastAPI app uses `Depends(get_db)`
  to get a Session. In your test, request the `pglite_engine` fixture and then
  override `get_db` to yield a Session from that engine. For example:

```python
from fastapi.testclient import TestClient
from myapp.main import app, get_db  # the FastAPI app and the original dependency
from sqlalchemy.orm import Session


def test_create_user_api(pglite_engine):
    # Override get_db to use pglite_engine
    def override_get_db():
        with Session(pglite_engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db

    client = TestClient(app)
    resp = client.post("/users/", json={"name": "Bob", "email": "[email protected]"})
    assert resp.status_code == 200
    # ... further assertions ...
```

In this snippet, we inject a new Session bound to the `pglite_engine` for each
request([4](https://www.xugj520.cn/archives/py-pglite-postgresql-testing-guide.html#:~:text=def%20test_create_user,pglite_engine%29%20as%20session%3A%20yield%20session)).
 The test client will call our override, thereby using the in-memory Postgres.
This ensures the API is tested against the ephemeral DB and **no data goes to
the real database**. After the test, you can remove the override if needed
(FastAPI’s `TestClient` typically resets overrides when disposed).

- **Flask or others:** If your app uses a global SQLAlchemy `db` object or
  sessionmaker, you can configure it for tests. For instance, create a PyTest
  fixture that **re-binds the session/engine** to the pglite engine. In
  Flask-SQLAlchemy, you might do
  `app.config["SQLALCHEMY_DATABASE_URI"] = pglite_engine.url` before
  initializing the app context for testing.

- **Manual injection:** For pure Python code, you might design your functions
  to accept a session or engine as a parameter. In tests, simply pass in
  `pglite_session` or `pglite_engine`. This is a form of dependency injection
  as well, making the code more testable. For example, if you have a repository
  function `def get_user_by_email(email: str, session: Session): ...`, in tests
  you can call `get_user_by_email("alice@example.com", pglite_session)` using
  the fixture.

Using dependency injection techniques ensures your **application code under
test uses the same test database**. This way, whether you call functions
directly or hit endpoints, everything is operating on the py-pglite Postgres.
The result is end-to-end tests that are isolated yet use realistic database
interactions.

## Generating Test Data with Factory Boy and Faker

Manually crafting test data can be tedious and can lead to repetitive tests.
**Factory Boy** is a popular library that helps create ORM model instances with
fake data easily, and **Faker** is used under the hood (or directly) to
generate realistic data (names, emails, etc.). When testing a SQLAlchemy
application, factories and fake data can make tests more concise and robust:

- **Define factories for your models:** A factory is a class that knows how to
  create a model object. For SQLAlchemy ORM, Factory Boy offers
  `SQLAlchemyModelFactory` which can even handle session persistence. For
  example, using the `User` model above, we can define a factory:

```python
import factory
from factory.alchemy import SQLAlchemyModelFactory
from faker import Faker

fake = Faker()


class UserFactory(SQLAlchemyModelFactory):
    class Meta:
        model = User
        sqlalchemy_session = None  # to be set later by a fixture
        sqlalchemy_session_persistence = False

    name = factory.LazyAttribute(lambda _: fake.name())
    email = factory.LazyAttribute(lambda _: fake.safe_email())
```

This factory will generate a `name` and `email` using Faker whenever a
UserFactory is built. We left `sqlalchemy_session` as None for now – we’ll
inject the actual session at test time.

- **Use a fixture to attach the session:** In tests, we want
  `UserFactory.create()` to automatically add the user to our `pglite_session`.
  We can achieve this by assigning the PyTest session to the factory before
  using it. One way is an autouse fixture that runs for each test and sets
  `UserFactory._meta.sqlalchemy_session = pglite_session`. Factory Boy’s docs
  suggest this
  approach([5](https://medium.com/@aasispaudelthp2/factoryboy-tutorial-with-sqlalchemy-and-pytest-1cda908d783a#:~:text=%40pytest,my_factory._meta.sqlalchemy_session%20%3D%20session)).
   For example:

```python
@pytest.fixture(autouse=True)
def _set_factory_session(pglite_session):
    UserFactory._meta.sqlalchemy_session = pglite_session
```

Now, whenever you call `UserFactory()`, it will use the provided session to
insert the User into the database. For instance,
`alice = UserFactory(name="Alice")` will create a new User with name "Alice"
(and a fake email) and add it to `pglite_session`. You can then `commit` the
session if needed (or set `sqlalchemy_session_persistence=True` to have Factory
Boy commit automatically after creation).

- **Quick data generation:** With factories, you can generate multiple records
  in one go. For example, Factory Boy allows creating batches:
  `UserFactory.create_batch(5)` will make five User records at
  once([5](https://medium.com/@aasispaudelthp2/factoryboy-tutorial-with-sqlalchemy-and-pytest-1cda908d783a#:~:text=,name%3D%27Volvo)).
   Each will have unique fake data for the fields. This is extremely handy for
  populating a test database with sample data. You can also override specific
  fields per call (e.g., `UserFactory(name="Specific Name")`) to test
  particular
  scenarios([5](https://medium.com/@aasispaudelthp2/factoryboy-tutorial-with-sqlalchemy-and-pytest-1cda908d783a#:~:text=Here%20are%20some%20code%20snippets,advantage%20of%20Factoryboy%E2%80%99s%20powerful%20features)).

- **Faker for direct use:** Even outside of Factory Boy, you can use **Faker**
  directly in tests to generate data for ad-hoc inserts or assertions. For
  example, use `fake.email()` to get a random email address, ensuring your test
  covers various inputs. Faker can generate consistent data if you set a seed
  (e.g., `Faker.seed(1234)`) for reproducibility.

Using Factory Boy and Faker makes tests more **expressive** – you declare what
kind of data you need without manually coming up with values. This can uncover
edge cases (e.g. names with non-ASCII characters, very long text, etc. from
Faker) and keeps your tests maintainable. It’s especially powerful in
integration with py-pglite: you can **create a complex object graph with one
factory call** (thanks to Factory Boy’s support for SubFactory
relations([5](https://medium.com/@aasispaudelthp2/factoryboy-tutorial-with-sqlalchemy-and-pytest-1cda908d783a#:~:text=model%20%3D%20Faker%28%27sentence%27%2C%20nb_words%3D1%29%20,OwnerFactory))),
 and have that data immediately persisted to the in-memory Postgres for your
test to use.

## Final Tips and Best Practices

Combining **SQLAlchemy**, **PyTest**, and **py-pglite** gives you a potent
testing setup that is fast, isolated, and faithful to your production
environment. Here are some parting best-practice tips for this setup:

- **Keep tests deterministic:** Because each test starts with a known empty
  database (or resets it), you can be confident that tests won’t flicker due to
  state bleed-over. If you use a shared DB for speed, be rigorous in cleaning
  up data between tests. Tools like `verify_database_empty(engine)` from
  py-pglite can assert that no data
  remains([4](https://www.xugj520.cn/archives/py-pglite-postgresql-testing-guide.html#:~:text=%E6%A3%80%E6%9F%A5%E6%95%B0%E6%8D%AE%E5%BA%93%E6%98%AF%E5%90%A6%E4%B8%BA%E7%A9%BA)).

- **Always commit or flush when needed:** Remember that SQLAlchemy’s Session
  won’t persist changes to the database until you commit (or autoflush
  triggers). Many a test has been puzzled by a query not returning data because
  a commit was forgotten. Commit in your test or use `session.flush()` before
  selecting, to be
  safe([4](https://www.xugj520.cn/archives/py-pglite-postgresql-testing-guide.html#:~:text=%E9%97%AE%E9%A2%98%20%E5%8F%AF%E8%83%BD%E5%8E%9F%E5%9B%A0%20%E8%A7%A3%E5%86%B3%E6%96%B9%E6%B3%95%20%E5%90%AF%E5%8A%A8%E8%B6%85%E6%97%B6%20%E7%BD%91%E7%BB%9C%E6%85%A2%E3%80%81Node,%E6%B8%85%E7%90%86%E4%B8%BB%E9%94%AE%E5%BA%8F%E5%88%97)).

- **Parallel testing:** If you run tests in parallel (e.g., with
  `pytest-xdist`), ensure each process has an isolated database. Py-pglite’s
  default of one DB per test should handle this, but if you share a
  session-scoped DB, you *cannot* reuse it across processes. You might
  configure separate ports for each worker or simply stick to function-scoped
  isolation for parallel runs.

- **Node.js dependency:** As noted, py-pglite currently relies on Node to run
  the WASM
  Postgres([2](https://void.abn.is/a-python-project-postgresql-and-wasm/#:~:text=1,using%20it%20with)).
   In a CI environment, make sure Node is installed. Once set up, the tests
  behave the same locally and in CI. The maintainers are exploring more direct
  WASM integration to drop the Node requirement in the
  future([2](https://void.abn.is/a-python-project-postgresql-and-wasm/#:~:text=1,using%20it%20with))([2](https://void.abn.is/a-python-project-postgresql-and-wasm/#:~:text=The%20Wasm%20,a%20Better%20Future)).

- **Use real Postgres features confidently:** Since py-pglite *is* Postgres,
  don’t shy away from using JSON fields, text search, `pg_trgm`, or other
  extensions in your application *and* in your tests. You can even enable
  extensions like `pgvector` in py-pglite for testing advanced
  features([1](https://github.com/wey-gu/py-pglite#:~:text=))([1](https://github.com/wey-gu/py-pglite#:~:text=from%20py_pglite%20import%20PGliteConfig%2C%20PGliteManager,psycopg%20import%20numpy%20as%20np)).
   Your tests can then validate functionality that would be impossible to test
  with SQLite or mocks.

By following this guide, you set up a robust testing environment for your
SQLAlchemy 2.x application. You get the **best of both worlds** – quick,
ephemeral databases as convenient as SQLite, and the full power and accuracy of
PostgreSQL. This allows you to write thorough tests (unit tests, integration
tests, even testing your API endpoints with the DB in play) with minimal
friction. In practice, teams find that such a setup **“shaves minutes from
every build, and hours from every week” by ensuring every test run starts from
a known good state with no manual DB management
overhead([3](https://hoop.dev/blog/the-simplest-way-to-make-postgresql-pytest-work-like-it-should/#:~:text=Why%20does%20PostgreSQL%20PyTest%20improve,and%20hours%20from%20every%20week))**.
 Happy testing!

**Sources:**

- Arun Babu Neelicattu, *"Python, PostgreSQL and Wasm walk into a pytest bar"*
  – Overview of py-pglite for in-process Postgres
  testing([2](https://void.abn.is/a-python-project-postgresql-and-wasm/#:~:text=The%20,also%20provides%20fixtures%20for%20Django))([2](https://void.abn.is/a-python-project-postgresql-and-wasm/#:~:text=,containers%20for%20every%20test%20run)).

- wey-gu (GitHub) – **py-pglite** README and examples (SQLAlchemy usage, async
  tips, extension
  support)([1](https://github.com/wey-gu/py-pglite#:~:text=%2A%20Zero%20config%20,SQLAlchemy%2C%20Django%2C%20psycopg%2C%20asyncpg))([1](https://github.com/wey-gu/py-pglite#:~:text=,engine%20%3D%20create_async_engine%28f%22postgresql%2Basyncpg%3A%2F%2F%7Bhost%7D%3A%7Bport%7D%2F%7Bdatabase)).

- High Efficiency Coder Blog –
  *"秒建PostgreSQL内存数据库：Python测试效率翻倍秘籍"* (Chinese) – In-depth
  guide on py-pglite usage and
  utilities([4](https://www.xugj520.cn/archives/py-pglite-postgresql-testing-guide.html#:~:text=from%20py_pglite%20import%20utils%20utils))([4](https://www.xugj520.cn/archives/py-pglite-postgresql-testing-guide.html#:~:text=def%20test_create_user,pglite_engine%29%20as%20session%3A%20yield%20session)).

- hoop.dev blog – *"PostgreSQL PyTest work like it should"* – Best practices
  for database test isolation and
  performance([3](https://hoop.dev/blog/the-simplest-way-to-make-postgresql-pytest-work-like-it-should/#:~:text=How%20do%20you%20connect%20PostgreSQL,performance%20while%20avoiding%20database%20bloat)).

- Aashish Paudel, *Factory Boy tutorial with SQLAlchemy and Pytest* – Usage of
  Factory Boy with SQLAlchemy (session fixture,
  `SQLAlchemyModelFactory`)([5](https://medium.com/@aasispaudelthp2/factoryboy-tutorial-with-sqlalchemy-and-pytest-1cda908d783a#:~:text=%40pytest,my_factory._meta.sqlalchemy_session%20%3D%20session))([5](https://medium.com/@aasispaudelthp2/factoryboy-tutorial-with-sqlalchemy-and-pytest-1cda908d783a#:~:text=,name%3D%27Volvo)).
