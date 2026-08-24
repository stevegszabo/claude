def build_filter(base_filter, **filters):
    """Build a PPDM filter expression, ANDing an optional base filter with
    substring matches on each given field (PPDM's `lk "%...%"` operator).
    """
    clauses = [base_filter] if base_filter else []
    for field, value in filters.items():
        if value:
            clauses.append('{} lk "%{}%"'.format(field, value))
    return " and ".join(clauses) if clauses else None
