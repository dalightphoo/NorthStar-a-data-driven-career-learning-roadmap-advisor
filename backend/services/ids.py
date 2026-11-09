def northstar_id_from_pk(user_id: int) -> str:
    high = user_id // 10000
    low = user_id % 10000
    return f"Interstellar-{high:04d}-{low:04d}"
