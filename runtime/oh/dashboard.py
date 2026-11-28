"""Read-only dashboard projections over the existing analytics index."""
from datetime import datetime, timedelta, timezone
import json

from .telemetry import delivery_cost_rows, rows

PAGE_SIZE = 20
DIFFICULTIES = ('simple', 'standard', 'complex')

# The table and KPIs use the start cohort. The delivery chart uses finish dates.
TASKS = """
    WITH selected AS (
        SELECT t.*, r.name, r.status run_status,
               EXISTS (SELECT 1 FROM collector_state c WHERE c.key=
                       'gap:task:'||t.run||':'||t.id) missing_start
        FROM tasks t JOIN runs r ON r.id=t.run WHERE {predicate} AND {period}
    ), facts AS (
        SELECT s.*,
               CASE WHEN NOT missing_start AND julianday(ended)>=julianday(started)
                    THEN COALESCE(wall_ms,ROUND((julianday(ended)-julianday(started))*86400000))
               END elapsed_ms
        FROM selected s
    )
"""

# Coverage uses the same attempt-start cohort as phase/model time. The usage trend
# has its own observation dates, which can include tokens from older attempts.
ATTEMPTS = """
    WITH selected AS (
        SELECT a.id, a.model, a.duration_ms,
               CASE a.phase WHEN 'repair' THEN 'implementation' ELSE a.phase END phase
        FROM attempts a LEFT JOIN runs r ON r.id=a.run
        WHERE a.started>=:start AND a.started<:end AND a.role!='orchestrator'
          AND (:project IS NULL OR COALESCE(a.project,r.project)=:project)
    ), observations AS (
        SELECT a.id,
               CASE WHEN COUNT(u.id)=COUNT(u.input+u.output)
                         AND COUNT(u.id)>0 THEN SUM(u.input+u.output) END tokens
        FROM selected a JOIN usage u ON u.attempt=a.id GROUP BY a.id
    )
"""


def delivery(db, params, tasks, *, by_finish=False):
    day = 'ended' if by_finish else 'started'
    return rows(db, tasks + f"""
        SELECT substr({day},1,10) day, difficulty, COUNT(*) delivered,
               COUNT(expected_reviews) reviewed, SUM(expected_reviews) reviews,
               SUM(expected_reviews=1) one_round, SUM(expected_reviews=2) two_rounds,
               SUM(expected_reviews>=3) more_rounds,
               COUNT(elapsed_ms) timed, SUM(elapsed_ms) elapsed_ms
        FROM facts WHERE status='completed' AND (:allow_missing_start OR NOT missing_start) GROUP BY day,difficulty ORDER BY day
    """, params)


def matched_change(current, previous, value, sample):
    def cohorts(days):
        result = {}
        for day in days:
            if day['difficulty'] in DIFFICULTIES and day[sample]:
                aggregate = result.setdefault(day['difficulty'], [0, 0])
                aggregate[0] += day[value]
                aggregate[1] += day[sample]
        return result

    recent, prior = cohorts(current), cohorts(previous)
    same_mix = [(min(count, prior[level][1]), amount/count, prior[level][0]/prior[level][1])
                for level, (amount, count) in recent.items() if level in prior]
    if sum(weight for weight, _, _ in same_mix) < 10:
        return None
    baseline = sum(weight * old for weight, _, old in same_mix)
    return sum(weight * new for weight, new, _ in same_mix) / baseline - 1 if baseline else None


def task_cost_coverage(db, params, tasks):
    return dict(db.execute(tasks + """
        SELECT COUNT(c.input+c.output) measured,
               CASE WHEN COUNT(*)=COUNT(c.input+c.output) THEN AVG(c.input+c.output) END average
        FROM facts t LEFT JOIN delivery_costs c ON c.run=t.run AND c.task=t.id
        WHERE t.status='completed' AND NOT t.missing_start
    """, params).fetchone())


def task_rows(db, params, tasks):
    page = rows(db, tasks + """
        SELECT run,id,title,difficulty,status,CASE WHEN NOT missing_start THEN started END started,
               name,run_status,expected_reviews,
               (SELECT SUM(a.duration_ms) FROM attempts a WHERE a.run=t.run AND a.task=t.id AND a.role!='orchestrator' AND a.phase!='correction'
                HAVING COUNT(*)=COUNT(a.duration_ms)
                   AND (COUNT(*)=t.expected_attempts OR t.status='feedback')) agent_ms,
               CASE WHEN expected_attempts>0 THEN
                 (SELECT SUM(tokens) FROM (
                    SELECT SUM(u.input+u.output) tokens
                    FROM attempts a LEFT JOIN usage u ON u.attempt=a.id WHERE a.run=t.run AND a.task=t.id AND a.role!='orchestrator' AND a.phase!='correction'
                    GROUP BY a.id HAVING COUNT(u.id)>0 AND COUNT(u.input+u.output)=COUNT(u.id)
                  ) HAVING COUNT(*)=t.expected_attempts AND
                      (SELECT COUNT(*) FROM attempts a WHERE a.run=t.run AND a.task=t.id AND a.role!='orchestrator' AND a.phase!='correction')=t.expected_attempts)
               END observed_tokens,
               (SELECT json_group_array(outcome) FROM
                    (SELECT a.outcome FROM attempts a WHERE a.run=t.run AND a.task=t.id AND a.role!='orchestrator' AND a.phase!='correction'
                     AND a.role='review' ORDER BY a.started,a.id)) review_outcomes
        FROM facts t ORDER BY t.started DESC,run,id LIMIT :limit OFFSET :offset
    """, params)
    for task in page:
        task['review_outcomes'] = json.loads(task['review_outcomes'])
    return page


def activity(db, params):
    usage = rows(db, """
        SELECT substr(u.at,1,10) day, COUNT(*) records,
               COUNT(u.cached+(u.input-u.cached)+u.output) stacked,
               SUM(CASE WHEN u.cached+u.input+u.output IS NOT NULL THEN u.cached END) cached,
               SUM(CASE WHEN u.cached+u.input+u.output IS NOT NULL THEN u.input-u.cached END) fresh,
               SUM(CASE WHEN u.cached+u.input+u.output IS NOT NULL THEN u.output END) output,
               SUM(u.input+u.output) tokens
        FROM usage u LEFT JOIN attempts a ON a.id=u.attempt LEFT JOIN runs r ON r.id=a.run
        WHERE u.at>=:start AND u.at<:end
          AND (:project IS NULL OR COALESCE(a.project,r.project)=:project)
        GROUP BY day ORDER BY day
    """, params)
    coverage = dict(db.execute(ATTEMPTS + """
        SELECT COUNT(*) attempts, COUNT(o.tokens) measured
        FROM selected a LEFT JOIN observations o ON o.id=a.id
    """, params).fetchone())
    phases = rows(db, ATTEMPTS + """
        SELECT phase, COUNT(*) attempts, COUNT(duration_ms) timed, SUM(duration_ms) agent_ms
        FROM selected WHERE phase IN ('assessment','implementation','review') GROUP BY phase
    """, params)
    models = rows(db, ATTEMPTS + """
        SELECT model, group_concat(DISTINCT phase) phases, COUNT(*) attempts,
               COUNT(duration_ms) timed, SUM(duration_ms) agent_ms, SUM(o.tokens) tokens,
               COUNT(o.tokens) measured
        FROM selected a LEFT JOIN observations o ON o.id=a.id
        WHERE model IS NOT NULL AND model != ''
        GROUP BY model HAVING COUNT(duration_ms)>0 ORDER BY agent_ms DESC,model LIMIT 4
    """, params)
    return {'usage': usage, 'coverage': coverage, 'phases': phases, 'models': models}


def diagnostics(db):
    data = rows(db, """
        SELECT key,value FROM collector_state WHERE key LIKE 'gap:%'
            OR key IN ('last_ingested','invalid_events') ORDER BY key
    """)
    values = {item['key']: item['value'] for item in data}
    try:
        invalid = json.loads(values.get('invalid_events', '[]'))
    except ValueError:
        invalid = None
    # The existing collector only retains an invalid batch summary in the index.
    return {'freshness': db.execute('SELECT MAX(at) FROM events').fetchone()[0],
            'last_ingested': values.get('last_ingested'),
            'invalid_records': len(invalid) if isinstance(invalid, list) else None,
            'gaps': [value for key, value in values.items() if key.startswith('gap:')]}


def task_predicate(bounds):
    fields = {'project': 'r.project', 'kind': 'r.work_kind', 'difficulty': 't.difficulty',
              'version': 'r.version'}
    clauses = [f'{column}=:{key}' for key, column in fields.items() if bounds.get(key)]
    attempt_filters = [f'a.{key}=:{key}' for key in ('model', 'phase') if bounds.get(key)]
    if attempt_filters:
        clauses.append('EXISTS (SELECT 1 FROM attempts a WHERE a.run=t.run AND a.task=t.id AND '
                       + ' AND '.join(attempt_filters) + ')')
    return ' AND '.join(clauses) or '1=1'


def filter_options(db):
    return {
        'kind': [row[0] for row in db.execute('SELECT DISTINCT work_kind FROM runs ORDER BY 1')],
        'difficulty': list(DIFFICULTIES),
        'version': [row[0] for row in db.execute('SELECT DISTINCT version FROM runs ORDER BY 1 DESC') if row[0]],
        'model': [row[0] for row in db.execute('SELECT DISTINCT model FROM attempts ORDER BY 1') if row[0]],
        'phase': [row[0] for row in db.execute('SELECT DISTINCT phase FROM attempts ORDER BY 1') if row[0]],
    }


def snapshot(db, bounds, offset=0, comparison=None):
    from .observability import ci_metrics

    params = bounds | {'start': bounds['from'], 'end': bounds['to'], 'project': bounds.get('project'),
                       'limit': PAGE_SIZE, 'offset': offset, 'allow_missing_start': False}
    start, end = (datetime.fromisoformat(params[key]) for key in ('start', 'end'))
    first = datetime.min.replace(tzinfo=timezone.utc)
    previous_start = start - min(end - start, start - first)
    baseline = bounds | {'from': previous_start.isoformat(timespec='milliseconds'),
                         'to': params['start']} | (comparison or {})
    prior_params = params | baseline | {'start': baseline['from'], 'end': baseline['to']}
    start_period = "t.started>=:start AND t.started<:end"
    tasks = TASKS.format(predicate=task_predicate(bounds), period=start_period)
    prior_tasks = TASKS.format(predicate=task_predicate(baseline), period=start_period)
    current = delivery(db, params, tasks)
    previous = delivery(db, prior_params, prior_tasks)
    finish_period = "t.status='completed' AND t.ended>=:start AND t.ended<:end"
    trend = delivery(db, params | {'allow_missing_start': True}, TASKS.format(
        predicate=task_predicate(bounds), period=finish_period), by_finish=True)
    total, started = db.execute(tasks + """
        SELECT COUNT(*), COUNT(CASE WHEN NOT missing_start THEN 1 END) FROM selected
    """, params).fetchone()
    projects = rows(db, """
        SELECT id,name FROM (SELECT project id, COALESCE(name,project) name,
            ROW_NUMBER() OVER(PARTITION BY project ORDER BY
                CASE WHEN work_kind='unknown' THEN 1 ELSE 0 END, started DESC,id DESC) ordinal
            FROM runs) WHERE ordinal=1 ORDER BY name,id
    """)
    return {'range': bounds, 'baseline': baseline,
            'delivery': trend, 'cohort': current, 'delivered': sum(day['delivered'] for day in current),
            'started': started, 'previous_delivered': sum(day['delivered'] for day in previous),
            'task_count': total, 'offset': offset, 'page_size': PAGE_SIZE,
            'has_runs': bool(projects),
            'delivery_samples': {
                'reviews_change': matched_change(current, previous, 'reviews', 'reviewed'),
                'time_change': matched_change(current, previous, 'elapsed_ms', 'timed')},
            'delivery_costs': delivery_cost_rows(db, bounds),
            'task_cost': task_cost_coverage(db, params, tasks),
            'tasks': task_rows(db, params, tasks), 'projects': projects, 'options': filter_options(db),
            'health': diagnostics(db) | {'ci': ci_metrics(db, bounds),
                'suggestions': [json.loads(item['payload']) | {'status': item['status']}
                    for item in rows(db, 'SELECT payload,status FROM recommendations ORDER BY created DESC LIMIT 3')]}} | activity(db, params)
