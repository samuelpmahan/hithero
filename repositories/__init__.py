"""All database queries, behind small functions (BE2-10).

Routes and jobs call these instead of building queries. Functions take
the session as their first argument and never commit; the caller decides
when a unit of work is done.

Many text columns are compared through cast(..., String): production
columns appear to be TEXT/NTEXT, which SQL Server can't compare directly.
The casts go away with the column migration in BE2-7.
"""
