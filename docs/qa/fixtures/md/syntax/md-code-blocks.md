### CB-01 — backtick fence with language

```python
def greet(name: str) -> str:
    return f"Hello, {name}"
```

### CB-02 — backtick fence without language

```
plain fenced block
second line
```

### CB-03 — tilde fence

~~~
tilde fenced block
~~~

### CB-04 — indented (4-space) code block

Paragraph before.

    indented code line one
    indented code line two

### CB-05 — blank lines inside a fenced block

```
first line

third line, after a blank line


sixth line, after two blank lines
```

### CB-06 — very long line

```
this_is_a_very_long_line_of_code = call_something(argument_one, argument_two, argument_three, argument_four, argument_five, argument_six)
```

### CB-07 — markdown syntax inside a fence is literal

```
# not a heading
- not a list
**not bold**
| not | a table |
```

### CB-08 — leading indentation inside a fence is kept

```yaml
root:
  child:
    grandchild: value
```

### CB-09 — fence containing a shorter fence

````
```
inner fence is literal
```
````

### CB-10 — fence directly after a paragraph, no blank line

A paragraph line.
```
fence right after paragraph
```
