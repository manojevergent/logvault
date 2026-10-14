#!/usr/bin/env python3
"""
Invoice API Logs - Automated Setup Script
Creates regional credentials and jobs for all tracked customers
"""

import requests
import json
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional

class InvoiceLogsSetup:
    def __init__(self, api_base: str = "http://localhost:8000"):
        self.api_base = api_base
        self.session = requests.Session()
        self.credentials = {}
        self.index_targets = {}

    def log(self, level: str, msg: str):
        """Print colored log messages"""
        colors = {
            'info': '\033[94m',
            'success': '\033[92m',
            'warning': '\033[93m',
            'error': '\033[91m',
            'reset': '\033[0m'
        }
        prefix = f"[{level.upper()}]".ljust(8)
        print(f"{colors.get(level, '')}{prefix}{msg}{colors['reset']}")

    def check_api(self) -> bool:
        """Verify API is accessible"""
        try:
            resp = self.session.get(f"{self.api_base}/health", timeout=5)
            if resp.status_code == 200:
                self.log('success', 'API is healthy')
                return True
        except Exception as e:
            self.log('error', f'API check failed: {e}')
        return False

    def create_credentials(self) -> Dict[str, int]:
        """Create regional credentials"""
        self.log('info', 'Creating Regional Credentials')
        print('=' * 60)

        regions = {
            'NV': {
                'label': 'Last9 - North Virginia',
                'slug': 'evergentuse1',
                'region_code': 'us-east-1',
                'token': 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJsYXN0OS5pbyIsImF1ZCI6WyJhcHAubGFzdDkuaW8iXSwiZXhwIjoxODUyNTM2NTY5LCJuYmYiOjE3ODkzNzgxNjksImlhdCI6MTc4OTM3ODE2OSwianRpIjoiZDQ1ODU3NzktN2UxNy00OTI5LWJmZjYtZTUwZDg1ZGU0Zjg1Iiwic2NvcGVzIjpbInJlYWQiXSwia2luZCI6InJlZnJlc2hfdG9rZW4iLCJlbWFpbCI6Im1hbm9qQGV2ZXJnZW50LmNvbSIsIm9yZ2FuaXphdGlvbl9zbHVnIjoiZXZlcmdlbnR1c2UxIiwidG9rZW5faWQiOiIwNTdlNjhmNy03MmFmLTRiNDgtYWUyNS05MzIyMmRiNTI4NDcifQ.tG-Qy7lEhKw5RvSy2NwL0HJdbn5Qx2rgWIZ2zrkhBQs'
            },
            'IR': {
                'label': 'Last9 - Frankfurt',
                'slug': 'evergenteuc1',
                'region_code': 'eu-central-1',
                'token': 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJsYXN0OS5pbyIsImF1ZCI6WyJhcHAubGFzdDkuaW8iXSwiZXhwIjoxODUyNTM2NzY4LCJuYmYiOjE3ODkzNzgzNjgsImlhdCI6MTc4OTM3ODM2OCwianRpIjoiMDA5ZTQwNzItZDJhMy00ZDNmLWIxMzQtMDQ1OTUzNzgyNjA5Iiwic2NvcGVzIjpbInJlYWQiXSwia2luZCI6InJlZnJlc2hfdG9rZW4iLCJlbWFpbCI6Im1hbm9qQGV2ZXJnZW50LmNvbSIsIm9yZ2FuaXphdGlvbl9zbHVnIjoiZXZlcmdlbnRldWMxIiwidG9rZW5faWQiOiI2YTM3ZmNlMy1hODNiLTRjNDQtOGQ2Yi0xMjBjMjYyZmIyNjYifQ.Zya5QWm9f_S939YAEm_YYC0mnt0oiLVjqv0hptTOKlA'
            },
            'SG': {
                'label': 'Last9 - Singapore',
                'slug': 'evergentapse1',
                'region_code': 'ap-southeast-1',
                'token': 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJsYXN0OS5pbyIsImF1ZCI6WyJhcHAubGFzdDkuaW8iXSwiZXhwIjoxODUyNTM2ODk5LCJuYmYiOjE3ODkzNzg0OTksImlhdCI6MTc4OTM3ODQ5OSwianRpIjoiMzk5M2MzMjYtODA3MS00ZWI4LWE1NTUtYjc4M2ZlNmNlZjA4Iiwic2NvcGVzIjpbInJlYWQiXSwia2luZCI6InJlZnJlc2hfdG9rZW4iLCJlbWFpbCI6Im1hbm9qQGV2ZXJnZW50LmNvbSIsIm9yZ2FuaXphdGlvbl9zbHVnIjoiZXZlcmdlbnRhcHNlMSIsInRva2VuX2lkIjoiMjE4ZGJjYzAtM2NhYy00YWMzLTkwY2YtNjhiOWJhMmY5MDI2In0.C6bk5Cq_ljp-5ZppxrEGt6psv8cBWSXW8PhSnwJtSRA'
            }
        }

        for region, data in regions.items():
            try:
                resp = self.session.post(
                    f"{self.api_base}/credentials",
                    json={
                        'label': data['label'],
                        'org_slug': data['slug'],
                        'refresh_token': data['token']
                    }
                )
                if resp.status_code == 200:
                    cred_id = resp.json().get('id')
                    self.credentials[region] = cred_id
                    self.log('success', f'{region} ({data["region_code"]}) → ID {cred_id}')
                else:
                    self.log('error', f'{region}: {resp.status_code} - {resp.text[:100]}')
            except Exception as e:
                self.log('error', f'{region}: {str(e)}')

        return self.credentials

    def get_index_target(self, region_code: str) -> Optional[int]:
        """Get or create UMServices index for region"""
        try:
            resp = self.session.get(f"{self.api_base}/indexes?region={region_code}")
            if resp.status_code == 200:
                indexes = resp.json()
                if isinstance(indexes, list) and indexes:
                    return indexes[0].get('id')
        except Exception as e:
            self.log('warning', f'Could not fetch indexes: {e}')
        return None

    def create_sample_job(self, region: str, customer: str, region_code: str,
                         phrases: List[str], ids: List[str]) -> Optional[int]:
        """Create a sample job for a customer"""
        if region not in self.credentials:
            self.log('error', f'No credential for region {region}')
            return None

        # Get index target
        index_id = self.get_index_target(region_code)
        if not index_id:
            self.log('warning', f'No index found for {region_code}, skipping job')
            return None

        try:
            end_epoch = int(time.time())
            start_epoch = end_epoch - (24 * 3600)  # Last 24 hours

            resp = self.session.post(
                f"{self.api_base}/jobs",
                json={
                    'credential_id': self.credentials[region],
                    'index_target_id': index_id,
                    'region_code': region_code,
                    'start_epoch': start_epoch,
                    'end_epoch': end_epoch,
                    'phrases': phrases,
                    'ids': ids,
                    'label': f'INVOICE_{customer}_TEST',
                    'customer': customer
                }
            )
            if resp.status_code == 200:
                job_id = resp.json().get('id')
                self.log('success', f'{customer} ({region}) → Job ID {job_id}')
                return job_id
            else:
                self.log('error', f'{customer}: {resp.status_code}')
        except Exception as e:
            self.log('error', f'{customer}: {str(e)}')
        return None

    def run_setup(self):
        """Execute full setup"""
        print()
        print('╔' + '═' * 58 + '╗')
        print('║' + ' Invoice API Logs - Automated Setup '.center(58) + '║')
        print('╚' + '═' * 58 + '╝')
        print()

        # Check API
        if not self.check_api():
            self.log('error', 'Cannot proceed - API not accessible')
            return False

        print()

        # Create credentials
        if not self.create_credentials():
            self.log('error', 'Failed to create credentials')
            return False

        print()

        # Create sample jobs
        self.log('info', 'Creating Sample Jobs')
        print('=' * 60)

        sample_jobs = [
            {
                'region': 'NV',
                'region_code': 'us-east-1',
                'customer': 'EKKL',
                'phrases': [
                    'ClassName CGetOAuthAccessTokenCommand SPAccountId',
                    'ClassName CGetCustomerServicesCommand SPAccountId'
                ],
                'ids': ['Ekkl']
            },
            {
                'region': 'SG',
                'region_code': 'ap-southeast-1',
                'customer': 'ABSCBN',
                'phrases': ['ABSCBNController getContactPostAction -- data comes from request'],
                'ids': ['ABSCBN']
            }
        ]

        for job_spec in sample_jobs:
            self.create_sample_job(
                job_spec['region'],
                job_spec['customer'],
                job_spec['region_code'],
                job_spec['phrases'],
                job_spec['ids']
            )

        print()

        # Print summary
        self.print_summary()
        return True

    def print_summary(self):
        """Print setup summary and next steps"""
        print('╔' + '═' * 58 + '╗')
        print('║' + ' Setup Complete '.center(58) + '║')
        print('╚' + '═' * 58 + '╝')
        print()

        if self.credentials:
            print('✓ Regional Credentials Created:')
            for region, cred_id in self.credentials.items():
                print(f'  • {region}: Credential ID {cred_id}')
            print()

        print('📋 Next Steps:')
        print('  1. Verify credentials in LogVault UI (Settings > Credentials)')
        print('  2. Create remaining jobs using LOGVAULT_JOB_SETUP_GUIDE.md')
        print('  3. Set up daily schedules at 00:00 UTC')
        print('  4. Run test extraction to verify Last9 connectivity')
        print('  5. Monitor initial jobs for any errors')
        print()

        print('📊 Tracked Customers by Region:')
        print('  • NV (9):  ANTENNA, EKKL, MINNO, MONGOLTV, SHAHID, VIKI...')
        print('  • IR (6):  ETV, EPL, FOOTBALL_ASSOCIATION, LIBERTY_GLOBAL...')
        print('  • SG (11): ABSCBN, ASTRO_SOOKA, ASTRO_NJOI, LIGHTBOX...')
        print('  • IN (1):  AHA')
        print()

        print('⚠️  Remember:')
        print('  • 8 customers require AND combinations (see SUMMARY.csv)')
        print('  • Start with smaller batches (5-10 customers per region)')
        print('  • Test one job thoroughly before bulk creation')
        print('  • Schedule daily extractions at 00:00 UTC')
        print()

if __name__ == '__main__':
    setup = InvoiceLogsSetup()
    success = setup.run_setup()
    exit(0 if success else 1)
