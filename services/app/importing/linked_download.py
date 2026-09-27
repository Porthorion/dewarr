"""Use the saved book association for one complete, unambiguous download."""

from uuid import UUID

from app.domain.catalog_titles import display_title, optional_subtitle_base
from app.domain.identity import normalized
from app.domain.work_graph import canonical_work
from app.importing.file_editions import attach_file_edition
from app.importing.match_evidence import group_evidence, language_key


def agrees_with_request(work, release, facts):
    # Missing tags are common in M4B files. Conflicting tags still require review.
    if facts.issues or work.metadata_fields.get("identity_rejected"):
        return False
    title = display_title(work.title)
    titles = {title, display_title(optional_subtitle_base(work.title))}
    authors = sorted(normalized(name) for name in work.authors)
    catalog_authors = set(authors)
    release_title = release.get("title", "")
    shown = display_title(release_title)
    head, separator, tail = release_title.partition(" - ")
    credit = normalized(tail.split(",")[0]) if separator else ""
    # The file may keep a series label after the catalog title, and an extra
    # co-author. That is not a different book. A different subtitle still is.
    file_title_exact = bool(facts.titles) and all(
        display_title(value) in titles for value in facts.titles
    )
    file_title_leading = bool(facts.titles) and all(
        display_title(value).split(":", 1)[0].strip() == title for value in facts.titles
    )
    file_authors_cover = bool(facts.authors) and all(
        catalog_authors <= set(value) for value in facts.authors
    )
    title_agrees = (
        shown in titles
        or (bool(separator) and display_title(head) in titles and credit in catalog_authors)
        or (file_title_leading and file_authors_cover and credit in catalog_authors)
    )
    if not title or not authors or not title_agrees:
        return False
    if facts.titles and not (file_title_exact or file_title_leading):
        return False
    if any(
        value != authors and not (file_title_leading and catalog_authors <= set(value))
        for value in facts.authors
    ):
        return False
    release_authors = sorted(normalized(name) for name in release.get("authors", []))
    if release_authors and release_authors != authors:
        return False
    if not release_authors and not facts.authors:
        return False
    if work.language and any(value != language_key(work.language) for value in facts.languages):
        return False
    return True


async def linked_version(db, approver, selection, inspection, group, grouping_revision):
    # Specific-edition requests must retain their stronger edition evidence.
    rule = selection.frozen["requirements"]
    if rule.get("version_id") or rule["medium"] != group.medium:
        return None
    work = await canonical_work(db, UUID(selection.frozen["origin_work_id"]))
    facts = group_evidence(inspection.snapshot, group)
    if not agrees_with_request(work, selection.frozen["release"], facts):
        return None
    version, _ = await attach_file_edition(
        db, approver, inspection.id, work.id, group.key, grouping_revision
    )
    return version
