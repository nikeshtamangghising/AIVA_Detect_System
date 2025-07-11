# AIVA_Detect_System - Telegram Bot Context File

## Project Overview
AIVA_Detect_System is a Telegram bot designed to prevent duplicate payments across multiple groups by monitoring payment details and alerting administrators when potential duplicates are detected.

## Core Functionality

### 1. Duplicate Detection System
- **Real-time monitoring** of all connected groups (up to 100+ groups)
- **Instant detection** of duplicate payment records
- **Automated alerts** to prevent double payments
- **24/7 operation** with continuous monitoring

### 2. Payment Data Types Monitored
- **Phone Numbers** (Mobile/Landline)
- **Bank Account Numbers**
- **eSewa Account Details**
- **Khalti Account Details**
- **Custom unique identifiers** (as added by admin)

### 3. User Roles & Permissions

#### Admin Users
- **Manual Data Management**
  - Add/remove payment data (phone numbers, account numbers) to database
  - Import/export payment data in bulk
  - Verify and validate payment records
- **System Configuration**
  - Manage bot settings and configurations
  - Add/remove groups from monitoring
  - Configure alert settings and thresholds
- **Record Management**
  - View all payment and duplicate records
  - Delete or flag records as invalid
  - Generate reports on detected duplicates

#### Manager Users
- Receive duplicate payment alerts
- View duplicate payment records
- Make decisions on payment processing
- Access reporting dashboard

#### Regular Users
- Send payment details in groups
- Receive hold notifications when duplicates detected

## Technical Requirements

### 1. Database Schema
```
payment_records:
- id (Primary Key)
- record_type (phone/bank/esewa/khalti/custom)
- record_value (actual number/account)
- group_id (Telegram group ID)
- message_id (Telegram message ID)
- user_id (Telegram user ID)
- timestamp (creation time)
- is_duplicate (boolean)
- processed (boolean)

groups:
- group_id (Primary Key)
- group_name
- group_type (monitoring/admin)
- status (active/inactive)
- added_by (admin user ID)
- added_date

admin_users:
- user_id (Primary Key)
- username
- role (admin/manager)
- permissions (JSON)
- added_date
```

### 2. Bot Commands

#### Admin Commands
- **Data Management**
  - `/add_phone <number> [notes]` - Add phone number to watchlist
  - `/add_account <bank> <account_number> [notes]` - Add bank account to watchlist
  - `/add_esewa <id> [notes]` - Add eSewa ID to watchlist
  - `/add_khalti <id> [notes]` - Add Khalti ID to watchlist
  - `/remove_data <id>` - Remove payment data from watchlist
  - `/list_data [type]` - View all watched payment data (filter by type)
  
- **System Management**
  - `/add_group` - Add current group to monitoring
  - `/remove_group <group_id>` - Remove group from monitoring
  - `/view_duplicates [status]` - View duplicate records (all/pending/resolved)
  - `/resolve_duplicate <id>` - Mark duplicate as resolved
  - `/stats` - View bot statistics
  - `/export_data [type]` - Export payment data (CSV/JSON)
  - `/import_data <file>` - Import payment data from file
  - `/admin_help` - Show all admin commands

#### Manager Commands
- `/duplicates` - View recent duplicates
- `/report` - Generate duplicate report
- `/status` - Check bot status
- `/manager_help` - Show manager commands

#### General Commands
- `/start` - Bot introduction
- `/help` - General help
- `/status` - Bot operational status

### 3. Detection Logic

#### Pattern Recognition
- Extract phone numbers (Nepal format: +977-XXX-XXX-XXXX)
- Extract bank account numbers (various formats)
- Extract eSewa/Khalti IDs
- Custom regex patterns for different payment methods

#### Duplicate Detection Algorithm
1. **Database Population**
   - **Automatic**: First occurrence of payment details is stored in the database
   - **Manual**: Admins can add payment details (numbers, accounts) directly
   - **Import**: Bulk import of payment data from external sources
   - All entries are checked against this combined database for duplicates

2. **Detection Process**
   - **Real-time scanning** of all incoming messages
   - **Pattern extraction** using regex to identify payment details
   - **Strict database comparison** - only matches against existing verified records
   - **No fuzzy matching** - exact matches required to prevent false positives
   - **Immediate alert** only for new entries matching existing database records

3. **Key Feature**:
   - Once a payment detail is in the database, any future identical entry will trigger an alert
   - This prevents repeated data entry mistakes from being flagged
   - Ensures only legitimate duplicate payments are detected

### 4. Alert System

#### Immediate Response
- Send "⚠️ HOLD - DO NOT PROCEED" message to group
- Tag relevant managers/admins
- Provide duplicate details and original record info

#### Alert Message Format
```
🚨 POTENTIAL DOUBLE PAYMENT DETECTED 🚨

⚠️ HOLD - DO NOT PROCEED ⚠️

📱 Payment Detail: [DETECTED_VALUE]
🔍 Type: [PAYMENT_TYPE]
📅 First Occurrence: [ORIGINAL_DATE]
👥 Original Group: [ORIGINAL_GROUP]
🆔 Transaction ID: [RECORD_ID]

@manager Please review before proceeding with payment.
```

### 5. Auto-Messaging & Group Management

#### Automated Group Onboarding
- **Auto-detect** when bot is added to new groups
- **Welcome Message** sent to group with brief bot introduction
- **Automatic Manager Detection** - Identifies group admins as managers
- **Manager Welcome DM** - Sends private message to all group managers with:
  - Bot usage instructions
  - Available commands
  - How to configure group settings
  - Support contact information

#### Group Monitoring
- Track group activity and message volume
- Monitor bot permissions in each group
- Auto-notify managers of any permission issues
- Handle group admin changes with automatic role updates

#### Performance Monitoring
- Track response times
- Monitor database performance
- Log all duplicate detections
- Generate usage statistics

### 6. Security & Privacy

#### Data Protection
- Encrypt sensitive payment data
- Implement access controls
- Audit trail for all actions
- Regular data backups

#### Bot Security
- Rate limiting to prevent spam
- Admin verification system
- Secure token management
- Error handling and logging

## Implementation Architecture

### 1. Bot Structure
```
AIVA_Detect_System/
├── main.py (Bot entry point)
├── handlers/
│   ├── admin_handlers.py
│   ├── manager_handlers.py
│   ├── detection_handlers.py
│   └── group_handlers.py
├── database/
│   ├── models.py
│   ├── operations.py
│   └── migrations.py
├── utils/
│   ├── pattern_detection.py
│   ├── alert_system.py
│   └── security.py
├── config/
│   ├── settings.py
│   └── bot_token.py
└── logs/
    ├── bot.log
    └── duplicates.log
```

### 2. External Dependencies
- **python-telegram-bot** - Telegram Bot API
- **SQLAlchemy** - Database ORM
- **PostgreSQL/MySQL** - Database
- **Redis** - Caching and session management
- **APScheduler** - Task scheduling
- **python-dotenv** - Environment management

### 3. Deployment Requirements
- **24/7 uptime** with auto-restart capabilities
- **Scalable architecture** to handle 100+ groups
- **Monitoring dashboard** for system health
- **Backup systems** for data protection
- **Load balancing** for high traffic

## Operational Workflows

### 1. Initial Setup Workflow
1. Admin adds bot to monitoring groups
2. Admin configures payment data patterns
3. Bot starts monitoring all groups
4. Admin tests duplicate detection
5. Manager permissions configured

### 2. Duplicate Detection Workflow
1. **Initial Setup**:
   - First occurrence of payment details is stored in the database
   - No alerts are generated for first-time entries

2. **Detection Process**:
   - **Auto-monitoring** begins immediately when bot is added to group
   - User sends payment details in monitored group
   - Bot extracts payment information using patterns
   - Bot checks if the exact details already exist in the database
   - Only triggers alert if it's a new entry matching existing database records
4. If duplicate found:
   - Send immediate hold alert
   - Notify managers
   - Log incident
   - Wait for admin action
5. If no duplicate:
   - Store record in database
   - Continue normal operation

### 3. Admin Management Workflow
1. Admin receives duplicate alert
2. Admin reviews both records
3. Admin decides if legitimate duplicate
4. Admin either:
   - Approves payment (marks as processed)
   - Removes duplicate record
   - Adds to exceptions list

## Success Metrics
- **Auto-onboarding Success**: >98% successful group onboarding rate
- **Manager Engagement**: >90% manager welcome message open rate
- **Detection Accuracy**: >99% accuracy (only flags actual database matches)
- **False Positive Rate**: <1% (virtually eliminated by only checking against existing records)
- **Response Time**: <2 seconds for duplicate alerts
- **Uptime**: 99.9% availability
- **Group Coverage**: Support for 100+ simultaneous groups

## Maintenance & Updates
- Regular database cleanup
- Performance optimization
- Security updates
- Feature enhancements based on user feedback
- Backup and recovery procedures

## Compliance & Legal
- Data privacy compliance (local regulations)
- Audit trail maintenance
- User consent management
- Data retention policies
- Security incident response procedures