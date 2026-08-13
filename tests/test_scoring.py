import unittest

from job_finder.models import Job
from job_finder.scoring import score


class ScoringTests(unittest.TestCase):
    def test_target_cloud_role_scores_as_actionable(self):
        job = Job(company='Example Product Technology', title='Cloud Engineer', location='Hyderabad, India', work_mode='Hybrid', experience='2-4 years', posting_date='Unknown', original_url_verified=True, description='Python Azure Linux CI/CD Docker Kubernetes Terraform REST APIs')
        scored = score(job)
        self.assertGreaterEqual(scored.match_score, 70)
        self.assertEqual(scored.recommendation, 'APPLY')
        self.assertEqual(scored.cloud_devops_match, 'High')

    def test_excluded_role_never_enters_report(self):
        scored = score(Job(company='Acme', title='Technical Support Engineer', posting_date='2026-08-12'))
        self.assertEqual(scored.recommendation, 'DO NOT INCLUDE')

    def test_unknown_details_are_not_invented(self):
        scored = score(Job(company='Acme', title='Software Engineer'))
        self.assertEqual(scored.salary, 'Not disclosed')
        self.assertEqual(scored.freshness, 'Unknown')

    def test_staff_and_principal_are_rejected(self):
        for title in ('Staff Engineer', 'Principal Engineer'):
            self.assertEqual(score(Job(company='Acme', title=title)).recommendation, 'DO NOT INCLUDE')

    def test_unknown_location_and_experience_cap_score(self):
        scored = score(Job(company='Product Tech', title='Software Engineer', description='Python JavaScript React Azure Linux CI/CD Kubernetes Terraform', posting_date='2026-08-12', original_url_verified=True))
        self.assertLessEqual(scored.match_score, 69)
        self.assertEqual(scored.confidence, 'LOW')

    def test_preferred_and_outside_locations(self):
        good = score(Job(company='Acme', title='Software Engineer', location='Hyderabad, India', experience='2-5 years', posting_date='2026-08-12', original_url_verified=True))
        bad = score(Job(company='Acme', title='Software Engineer', location='Mumbai, India', experience='2-5 years', posting_date='2026-08-12', original_url_verified=True))
        self.assertTrue(good.location_verified); self.assertEqual(bad.recommendation, 'DO NOT INCLUDE')

    def test_months_are_not_read_as_years(self):
        from job_finder.scoring import _years
        self.assertEqual(_years("24 months"), (2.0, 2.0))
        self.assertEqual(_years("18 months"), (1.5, 1.5))
        self.assertEqual(_years("1.5 yrs"), (1.5, 1.5))
        self.assertEqual(_years("3-16 yrs"), (3.0, 16.0))

    def test_location_score_is_tiered_and_field_scoped(self):
        from job_finder.scoring import location_points
        mk = lambda loc: Job(company='A', title='Software Engineer', location=loc,
                             description='we also have an office in india')
        self.assertEqual(location_points(mk('Hyderabad, India')), 10)
        self.assertEqual(location_points(mk('Bengaluru, India')), 5)
        self.assertEqual(location_points(mk('Berlin, Germany')), 0)
        self.assertEqual(location_points(mk('Unknown')), 0)

    def test_apply_immediately_requires_high_confidence(self):
        job = score(Job(company='Product Technology', title='Software Engineer', location='Hyderabad, India', experience='2-5 years', posting_date='Unknown', original_url_verified=True, description='Python Java React Azure Linux CI/CD Kubernetes Terraform'))
        self.assertEqual(job.confidence, 'MEDIUM')
        self.assertNotEqual(job.recommendation, 'APPLY IMMEDIATELY')
