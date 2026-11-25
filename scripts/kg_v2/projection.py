"""Source assertions remain stored even when a newer interpretation supersedes them."""


def active_assertion(value):
    return (value.get('projectionStatus') != 'superseded' and not value.get('supersededBy')
            and value.get('reviewStatus') != 'rejected')
