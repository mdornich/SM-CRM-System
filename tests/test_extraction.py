"""Spec §8 extraction-honesty tests (build-prompt tests 1-3, 11)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from relationship_intel.extraction.extractor import Extractor
from relationship_intel.extraction.schemas import (
    ApprovalStatus,
    ExtractedRelationshipIntelligence,
    LeadType,
    RecommendedCRMAction,
    ReviewStatus,
    SuccessionLeadProfile,
    TimingWindow,
)
from relationship_intel.intake.local_folder import LocalFolderSource


@pytest.fixture
def extractions(settings, samples_dir) -> dict[str, ExtractedRelationshipIntelligence]:
    extractor = Extractor(settings)
    return {
        raw.source_id: extractor.extract(raw)
        for raw in LocalFolderSource(samples_dir).iter_transcripts()
    }


def _profile(eri, name):
    return next(p for p in eri.lead_profiles if p.person_name == name)


def test_warm_prospect_classified_conservatively_but_correctly(extractions, samples_dir):
    eri = extractions["granola-note-0001"]
    bob = _profile(eri, "Bob Smith")
    assert bob.lead_type == LeadType.warm
    assert bob.timing_window == TimingWindow.months_3_6
    assert bob.succession_signal_score >= 50
    assert bob.exit_or_transition_signal is True
    assert bob.business_owner_signal is True
    # Evidence must quote the transcript verbatim.
    raw_text = (samples_dir / "2026-06-30-granola-bob-smith-succession-intro.md").read_text()
    assert bob.evidence_snippets
    for snippet in bob.evidence_snippets:
        assert snippet in raw_text
    bob_person = next(p for p in eri.people if p.name == "Bob Smith")
    assert bob_person.email == "bob@smithhvac.com"


def test_referral_source_is_not_a_prospect(extractions):
    eri = extractions["granola-note-0002"]
    sarah = _profile(eri, "Sarah Chen")
    assert sarah.lead_type == LeadType.referral_source
    assert sarah.stage.value == "nurture"
    assert sarah.evidence_snippets
    # Referral language must not read as the referrer's own transition intent.
    assert sarah.exit_or_transition_signal is not True


def test_irrelevant_transcript_is_not_fit_with_no_fabrication(extractions):
    eri = extractions["granola-note-0003"]
    tom = _profile(eri, "Tom Rivera")
    assert tom.lead_type == LeadType.not_fit
    assert tom.evidence_snippets  # even not_fit carries evidence
    tom_person = next(p for p in eri.people if p.name == "Tom Rivera")
    assert tom_person.email is None  # transcript has no email; none invented
    assert tom.suggested_message is None


def test_every_artifact_is_labeled_mock(extractions):
    for eri in extractions.values():
        assert eri.llm_provider == "mock"
        assert eri.lens_version.startswith("succession-v")
        assert eri.review_status == ReviewStatus.unreviewed


def test_classification_without_evidence_is_rejected():
    with pytest.raises(ValidationError):
        SuccessionLeadProfile(person_name="X", lead_type="warm", evidence_snippets=[])


def test_unknown_lead_type_allows_missing_evidence_and_null_fields():
    profile = SuccessionLeadProfile(person_name="X")
    assert profile.lead_type == LeadType.unknown
    assert profile.timing_window == TimingWindow.unknown
    assert profile.business_owner_signal is None
    assert profile.next_best_action is None


def test_out_of_vocabulary_enum_rejected():
    with pytest.raises(ValidationError):
        SuccessionLeadProfile(person_name="X", lead_type="scorching", evidence_snippets=["e"])


def test_action_approval_defaults_to_proposed():
    action = RecommendedCRMAction(action="create_task", target="Bob Smith")
    assert action.approval_status == ApprovalStatus.proposed
