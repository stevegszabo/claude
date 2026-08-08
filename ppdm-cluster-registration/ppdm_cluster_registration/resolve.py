def resolve_id(list_fn, resource_label, id_flag, name=None, id=None):
    """Resolve a resource ID from either an explicit id or a name lookup.

    `list_fn` is called as `list_fn(name=name)` and must return a list of
    matching resources (each a dict with an "id" key) -- e.g. bound to
    CredentialsAPI.list or RegistrationsAPI.list. Raises ValueError if
    neither id nor name is given, or if name does not resolve to exactly
    one match.
    """
    if id:
        return id
    if not name:
        raise ValueError("Either id or name must be provided")
    matches = list_fn(name=name)
    if len(matches) == 0:
        raise ValueError("No {} found matching name: {}".format(resource_label, name))
    if len(matches) > 1:
        raise ValueError(
            "{} name '{}' matched {} results; use {} instead".format(
                resource_label.capitalize(), name, len(matches), id_flag
            )
        )
    return matches[0]["id"]
