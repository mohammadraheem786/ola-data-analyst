(
    "UNION ALL metadata SELECT",
    """
    SELECT 'ride_id' AS column_name
    UNION ALL
    SELECT 'rider_id' AS column_name
    """,
    True
),
(
    "UNION ALL accessing another schema",
    """
    SELECT 'ride_id' AS column_name
    UNION ALL
    SELECT name FROM [dbo].[users]
    """,
    False
),