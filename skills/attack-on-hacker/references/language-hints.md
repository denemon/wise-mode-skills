# Language / Framework Hints

After detecting the stack, prioritize the stack-specific sinks below. Not exhaustive — these are where real CVEs cluster.

**Node.js / Express / NestJS**
- `child_process.exec` / `execSync` with any user-controlled fragment.
- `path.join` / `fs.*` with user input (path traversal, especially with `..`).
- `eval`, `Function()`, `vm.runInNewContext` on user data.
- Untrusted `Object.assign` / spread / `lodash.merge` — prototype pollution → gadget chains.
- `res.redirect(req.query.next)` — open redirect.
- Unsafe template engine flags: `pug` / `ejs` with HTML-unescaped interpolation.

**Python / Django / Flask / FastAPI**
- `pickle.loads`, `yaml.load` without `SafeLoader`, `marshal.loads` on user bytes.
- `subprocess.*` with `shell=True` and any user-controlled arg.
- Django: `mark_safe`, `format_html` misuse, `extra(where=...)`, `RawSQL`, `DEBUG=True` leaked to prod.
- Flask: `render_template_string(user_input)`.
- `eval` / `exec` reachable from request handlers.
- `requests.get(user_url)` with no host allowlist — SSRF to cloud metadata (`169.254.169.254`).

**Java / Spring / Spring Boot**
- SpEL injection: user input in `@Value`, `SpelExpressionParser`, or `MethodSecurityExpressionRoot`.
- `ObjectInputStream.readObject` on user bytes (Java deserialization).
- JNDI lookup with user-controlled name (Log4Shell-class).
- `Runtime.exec` / `ProcessBuilder` with concatenated strings.
- Spring Security: `permitAll()` on sensitive routes, missing `@PreAuthorize`, default `CsrfFilter` disabled.
- XXE: `DocumentBuilderFactory` without `disallow-doctype-decl` and external-entity features disabled.

**Go**
- `text/template` rendering HTML instead of `html/template`.
- `exec.Command("sh", "-c", userString)` patterns (the safe form is `exec.Command(name, args...)`).
- `unsafe` package usage, especially with pointer arithmetic on user-derived lengths.
- Integer truncation across `int` / `int32` / `int64` boundaries leading to short-buffer bugs.
- `database/sql`: string-concatenated queries instead of placeholders.
- `net/http`: missing `Timeout` on `http.Client` — SSRF amplification and slow-loris DoS.

**Rust**
- `unsafe` blocks combined with pointer arithmetic on user-derived lengths.
- `unwrap` / `expect` / `panic!` reachable from untrusted parsers (DoS via panic).
- `serde_json::from_str` of untyped values without size limits.
- `Command::new("sh").arg("-c").arg(user)` style invocations.

**SQL across all stacks**
- String-concatenated queries — even with apparent escaping.
- Dynamic `ORDER BY` / column names / table names that bypass parameterization.
- `LIKE` with user input that includes wildcards (no escaping of `%` / `_`).
