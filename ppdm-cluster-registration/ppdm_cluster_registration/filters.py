def build_filter(base_filter, name=None, id=None):
    """Build a PPDM filter expression, ANDing an optional base filter with
    substring matches on id and/or name (PPDM's `lk "%...%"` operator).
    """
    clauses = [base_filter] if base_filter else []
    if id:
        clauses.append('id lk "%{}%"'.format(id))
    if name:
        clauses.append('name lk "%{}%"'.format(name))
    return " and ".join(clauses) if clauses else None
