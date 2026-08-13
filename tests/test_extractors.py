import unittest
from job_finder.extractors import (extract_experience, derive_company_title,
                                   normalize_location, terms, cloud_match, skill_gaps)


class ExperienceTests(unittest.TestCase):
    def test_plus_forms_never_become_ranges(self):
        for text, want in [("Requirements: 7+ years of professional experience.", "7+ yrs"),
                           ("We need 1+ years experience with Node.", "1+ yrs"),
                           ("Qualifications: 8+ years in DevOps.", "8+ yrs"),
                           ("What you bring: 10+ years platform engineering.", "10+ yrs"),
                           ("Minimum 4 years of relevant experience.", "4+ yrs")]:
            self.assertEqual(extract_experience(text), want)

    def test_real_ranges_survive(self):
        self.assertEqual(extract_experience("Total Exp - 3- 16 Years"), "3-16 yrs")
        self.assertEqual(extract_experience("Years of Experience: 3 - 6 Yrs"), "3-6 yrs")
        self.assertEqual(extract_experience("Experience Level: 1-2 years"), "1-2 yrs")

    def test_fresher_and_unknown(self):
        self.assertEqual(extract_experience("Looking for a fresher."), "0-1 yrs")
        self.assertEqual(extract_experience("No numbers here at all."), "Unknown")


class CompanyTitleTests(unittest.TestCase):
    def test_ats_slug_beats_page_title(self):
        c, t = derive_company_title(
            "https://jobs.lever.co/pointclickcare/94b85a28-9893-48c5-a2bb-1a2b",
            "Intrmediate AI Enabled DevOps Engineer - PointClickCare")
        self.assertEqual(c, "Pointclickcare")
        self.assertIn("DevOps Engineer", t)

    def test_title_dash_is_not_a_company_separator(self):
        c, t = derive_company_title(
            "https://jobs.lever.co/kobie/98fb2c71-81f0-4ec6-b047-65acb8a5d1e2",
            "Lead Cloud Engineer - Remote")
        self.assertEqual(c, "Kobie")
        self.assertNotEqual(t, "Remote")

    def test_redundant_company_prefix_is_stripped_from_title(self):
        c, t = derive_company_title(
            "https://jobs.lever.co/jumpcloud/756b176a-817b-4088-8eda-af8b",
            "Jumpcloud - Software Engineer, Auth & Access - India")
        self.assertEqual(c, "Jumpcloud")
        self.assertEqual(t, "Software Engineer, Auth & Access - India")


class LocationTests(unittest.TestCase):
    def test_marketing_copy_is_rejected(self):
        for junk in ["Join our India Tech Hub - Be among the first hires!",
                     "[Jobs in India](https://in.jooble.org/)",
                     "LiveRefreshed daily India jobs",
                     "CSC GENERATION (Shared Services- India) - Engineering /"]:
            self.assertEqual(normalize_location(junk, "Cloud Engineer", "Acme")[0], "Unknown")

    def test_real_locations_pass(self):
        self.assertEqual(normalize_location("Hyderabad, India", "E", "A")[0], "Hyderabad, India")
        self.assertEqual(normalize_location("Remote - India", "E", "A")[0], "Remote - India")
        self.assertEqual(normalize_location("Bengaluru, Karnataka, India", "E", "A")[0], "Bengaluru, India")
        self.assertEqual(normalize_location("Noida", "E", "A")[0], "Noida")


class ScoringHelperTests(unittest.TestCase):
    def test_word_boundaries(self):
        got = terms("we use javascript and node.js and react.js",
                    {"java", "javascript", "node", "node.js", "react", "react.js"})
        self.assertEqual(got, ["javascript", "node.js", "react.js"])

    def test_cloud_match_discriminates(self):
        self.assertEqual(cloud_match(
            "Kubernetes, Docker, Terraform, AWS, SRE, CI/CD, cloud infrastructure automation.")[0], "High")
        self.assertEqual(cloud_match(
            "We build React UIs, deployed to the cloud with automated CI/CD on our platform.")[0], "Medium")
        self.assertEqual(cloud_match(
            "Build Java REST services backed by PostgreSQL. Write unit tests.")[0], "Low")

    def test_skill_gaps_are_job_specific(self):
        mine = {"python", "java", "azure", "ci/cd", "docker", "postgresql"}
        self.assertEqual(skill_gaps("Java, PostgreSQL, Kubernetes and Terraform on AWS", mine),
                         ["aws", "kubernetes", "terraform"])
        self.assertEqual(skill_gaps("Python and Azure with CI/CD pipelines", mine), [])


if __name__ == "__main__":
    unittest.main()
