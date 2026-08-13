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
        from job_finder.scoring import location_points
        good = score(Job(company='Acme', title='Software Engineer', location='Hyderabad, India', experience='2-5 years', posting_date='2026-08-12', original_url_verified=True))
        elsewhere_in_india = score(Job(company='Acme', title='Software Engineer', location='Mumbai, India', experience='2-5 years', posting_date='2026-08-12', original_url_verified=True))
        self.assertTrue(good.location_verified)
        self.assertTrue(elsewhere_in_india.location_verified)
        self.assertEqual(location_points(elsewhere_in_india), 5)

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

    def test_jd_mentioning_sales_is_not_a_sales_job(self):
        from job_finder.scoring import is_excluded
        self.assertFalse(is_excluded(Job(company='A', title='Software Engineer',
                                         description='Partner with sales engineering on escalations.')))
        self.assertTrue(is_excluded(Job(company='A', title='Sales Engineer')))
        self.assertTrue(is_excluded(Job(company='A', title='Technical Support Engineer')))

    def test_remote_must_be_india_eligible(self):
        from job_finder.scoring import location_points
        mk = lambda loc: Job(company='A', title='Software Engineer', location=loc)
        self.assertEqual(location_points(mk('Remote - India')), 10)
        self.assertEqual(location_points(mk('Noida')), 10)
        self.assertEqual(location_points(mk('Bengaluru, India')), 5)
        self.assertEqual(location_points(mk('Remote - Canada')), 0)
        self.assertEqual(location_points(mk('Remote')), 0)
        self.assertEqual(location_points(mk('Minneapolis, MN')), 0)

    def test_board_postings_are_never_rejected_for_age(self):
        from job_finder.scoring import is_stale
        old = Job(company='A', title='Software Engineer', source='Lever board API (meesho)')
        old.freshness = 'Older than 14 days'
        self.assertFalse(is_stale(old))
        scraped = Job(company='A', title='Software Engineer', source='Firecrawl web search')
        scraped.freshness = 'Older than 14 days'
        self.assertTrue(is_stale(scraped))

    def test_architecture_is_not_a_principal_role(self):
        from job_finder.scoring import classify_seniority
        self.assertEqual(classify_seniority('Software Engineer, Data Architecture'), 'MID')
        self.assertEqual(classify_seniority('Engineer, Leadership Tools'), 'MID')
        self.assertEqual(classify_seniority('Solutions Architect'), 'PRINCIPAL')
        self.assertEqual(classify_seniority('Tech Lead'), 'LEAD')

    def test_board_freshness_uses_the_long_scale(self):
        from job_finder.scoring import freshness
        self.assertEqual(freshness('2026-07-28', 'Lever board API (x)')[1], 4)
        self.assertEqual(freshness('2026-07-28', 'Firecrawl web search')[1], 0)

    def test_salary_is_parsed_not_grepped(self):
        from job_finder.scoring import salary_lpa, salary_points
        self.assertEqual(salary_lpa('INR 1,200,000 - 1,800,000'), 12.0)
        self.assertEqual(salary_points('INR 1,200,000 - 1,800,000'), 5)
        self.assertEqual(salary_points('INR 600,000 - 900,000'), 1)
        self.assertIsNone(salary_lpa('USD 150,000 - 200,000'))
        self.assertEqual(salary_points('Not disclosed'), 0)

    def test_role_tiers(self):
        from job_finder.scoring import role_points
        self.assertEqual(role_points('Software Engineer, Auth & Access'), 20)
        self.assertEqual(role_points('Software Development Engineer II'), 20)
        self.assertEqual(role_points('Backend Developer'), 20)
        self.assertEqual(role_points('Site Reliability Engineer'), 14)
        self.assertEqual(role_points('Full Stack Developer'), 14)
        self.assertEqual(role_points('Systems Engineer'), 9)
        self.assertEqual(role_points('Marketing Manager'), 0)
