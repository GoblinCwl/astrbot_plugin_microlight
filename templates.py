"""Plain-text notification templates; only explicit variables are substituted."""
import re
from datetime import datetime, timezone, timedelta

DEFAULT_TEMPLATES = {'alerts': '[微光集 · 告警中心] {title}\n编号：{recordId}\n级别：{level}\n状态：{status}\n{summary}\n时间：{occurredAt}', 'feedback': '[微光集 · 问题反馈] {title}\n编号：{recordId}\n状态：{status}\n{summary}\n时间：{occurredAt}', 'friends': '[微光集 · 友链申请] {title}\n编号：{recordId}\n状态：{status}\n{summary}\n时间：{occurredAt}'}


def render_message(event: dict, config: dict) -> str:
    kind = event['kind']
    template = config.get('template_' + kind)
    if not isinstance(template, str) or not template.strip():
        template = DEFAULT_TEMPLATES[kind]
    values = {key: str(event.get(key, '')) for key in
              ('id', 'kind', 'recordId', 'title', 'summary', 'status', 'occurredAt')}
    try:
        stamp = datetime.fromisoformat(str(event.get('occurredAt', '')).replace('Z', '+00:00'))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        values['occurredAt'] = stamp.astimezone(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M:%S')
    except (ValueError, TypeError):
        pass
    values['category'] = {'alerts': '告警中心', 'feedback': '问题反馈', 'friends': '友链申请'}[kind]
    values['level'] = {'warning': '警告', 'error': '错误'}.get(event.get('level'), '')
    # Single-pass replacement keeps event content literal and leaves unknown variables intact.
    return re.sub(r'\{([A-Za-z][A-Za-z0-9_]*)\}',
                  lambda match: values.get(match[1], match[0]), template)
