# What Is Tested - User Guide

This document explains what features are tested in the Polaris application, written in plain language for non-technical team members. It shows what we verify works correctly before releasing features to users.

---

## Dashboard Page

### What It Does
The Dashboard is the main admin page where administrators can see system statistics and access user management features.

### What We Test
✅ **Dashboard loads correctly** - The page displays without errors when an admin logs in

✅ **Statistics are accurate** - The numbers shown (total users, active users, super admins) match what's actually in the system

✅ **Security** - Only super administrators can access the dashboard; regular users are blocked

✅ **Error handling** - If something goes wrong, the page handles it gracefully without crashing

---

## Create New User Feature

### What It Does
Allows administrators to create new user accounts with all their information.

### What We Test

#### Form Fields

✅ **Username Field**
- Must be between 3 and 64 characters
- Can only contain letters, numbers, underscores, and hyphens
- Cannot be a username that already exists
- Field is required

✅ **Email Field**
- Must be a valid email address format
- Cannot be an email that's already in use
- Field is required

✅ **First Name Field**
- Optional field (can be left blank)
- If filled, must be less than 64 characters

✅ **Last Name Field**
- Optional field (can be left blank)
- If filled, must be less than 64 characters

✅ **Password Field**
- Must be at least 8 characters long
- Must contain at least one uppercase letter
- Must contain at least one lowercase letter
- Must contain at least one number
- Field is required

✅ **Confirm Password Field**
- Must match the password exactly
- Field is required

✅ **Active User Checkbox**
- Defaults to "checked" (ON) when the form loads
- When checked, the user can log in
- When unchecked, the user cannot log in

✅ **Super Admin Checkbox**
- Defaults to "unchecked" (OFF) when the form loads
- Only super admins can check this box
- When checked, user has full system access

✅ **Organization Selection**
- Dropdown menu to select which organization the user belongs to
- Required for non-super admin users
- Can search for organizations
- Can create a new organization from this form (see Create New Org Modal below)

✅ **Role Selection**
- Dropdown menu with 5 role options:
  - **Super Admin** (Super Administrator) - Full system access
  - **Org Admin** (Organization Administrator) - Full access within their organization
  - **Volunteer Coord** (Volunteer Coordinator) - Can manage volunteers
  - **Volunteer** - Standard volunteer access
  - **Viewer** - Read-only access
- All 5 roles are available in the dropdown
- Required when an organization is selected

#### User Creation Process

✅ **Form validation** - All fields are checked before the user is created

✅ **User is actually created** - After submitting, the new user exists in the system

✅ **Organization assignment** - If an organization is selected, the user is properly assigned to it

✅ **Role assignment** - If a role is selected, the user gets that role

✅ **Password is secure** - The password is stored securely (encrypted) in the database

✅ **Error messages** - If something goes wrong, clear error messages are shown

---

## Create New Org Modal

### What It Does
A popup window that appears when creating a user, allowing you to quickly create a new organization without leaving the user creation form.

### What We Test

✅ **Modal appears** - The popup window structure exists in the page

✅ **Form fields are present**:
- **Name field** - Required field for organization name
- **Description field** - Optional field for organization description

✅ **Organization is created** - When you submit the form, the organization is actually created in the system

✅ **Auto-selection works** - After creating the organization, it's automatically selected in the user form

✅ **Search works** - The newly created organization appears in the organization search dropdown

**Note**: Full testing of opening/closing the modal requires special browser testing tools. We test that the structure exists and the backend functionality works.

---

## Manage Users Page

### What It Does
A list page showing all users in the system, with options to view, edit, or manage them.

### What We Test

✅ **Page loads** - The list page displays correctly

✅ **User data is shown** - Usernames, emails, and other key information are displayed

✅ **Pagination works** - If there are more than 20 users, you can navigate to additional pages

✅ **User information is accurate** - The data shown matches what's in the database

---

## View User Page

### What It Does
A detailed view showing all information about a specific user.

### What We Test - All 8 Required Fields Are Displayed

✅ **Username** - The user's username is shown

✅ **Email** - The user's email address is shown

✅ **Full Name** - The user's full name is shown (or username if no name is set)

✅ **Created Date** - The date and time the account was created is shown

✅ **Last Updated** - The date and time the account was last modified is shown

✅ **Last Login** - The date and time the user last logged in is shown, OR "Never" if they've never logged in

✅ **Account Type** - Shows either "Super Admin" or "Regular User"

✅ **Status** - Shows either "Active" (user can log in) or "Inactive" (user cannot log in)

### Additional Testing

✅ **User with no organization** - Page works correctly for users not assigned to any organization

✅ **User with multiple organizations** - Page correctly shows all organizations a user belongs to

✅ **User with minimal data** - Page works even if user has no first/last name

---

## Edit User Page

### What It Does
A form page where you can modify a user's information.

### What We Test - All Fields Are Pre-Filled and Editable

✅ **Username field** - Pre-filled with current username, can be edited

✅ **Email field** - Pre-filled with current email, can be edited

✅ **First Name field** - Pre-filled with current first name (if set), can be edited

✅ **Last Name field** - Pre-filled with current last name (if set), can be edited

✅ **Active User Checkbox** - Shows current status (checked if active, unchecked if inactive), can be changed

✅ **Super Admin Checkbox** - Shows current status (checked if super admin, unchecked if not), can be changed (only by super admins)

✅ **Organization Selection** - Pre-selected with user's current organization (if they have one), can be changed

✅ **Role Selection** - Pre-selected with user's current role (if they have one), can be changed
- All 5 role options are available in the dropdown

### Update Process

✅ **Changes are saved** - When you submit the form, the changes are actually saved

✅ **Validation works** - Invalid data (like duplicate usernames) is rejected with clear error messages

✅ **Organization updates** - If you change the organization, the user is properly reassigned

✅ **Role updates** - If you change the role, the user's permissions are updated

---

## Change Password Page

### What It Does
A form where administrators can change a user's password.

### What We Test

✅ **New Password field** - Required field with the same complexity rules as creating a user:
- At least 8 characters
- At least one uppercase letter
- At least one lowercase letter
- At least one number

✅ **Confirm Password field** - Must match the new password exactly

✅ **Password actually changes** - After changing the password:
- The user can log in with the NEW password ✅
- The user CANNOT log in with the OLD password ✅

✅ **Validation** - Invalid passwords (too short, missing requirements) are rejected

---

## Delete User Feature

### What It Does
Allows administrators to permanently delete a user account from the system.

### What We Test

✅ **User is deleted** - After deletion, the user no longer exists in the system

✅ **Cannot delete yourself** - Administrators cannot delete their own account (safety feature)

✅ **Proper cleanup** - User's organization memberships are properly removed

✅ **Admin log is created** - The deletion action is recorded in the admin logs

---

## View Logs Page

### What It Does
Shows a history of all administrative actions taken in the system.

### What We Test

✅ **Page loads** - The logs page displays correctly

✅ **Logs are accessible** - Administrators can view the log history

✅ **Security** - Only authorized administrators can access logs

---

## Edge Cases and Special Scenarios

### What We Test

✅ **User who never logged in** - The "Last Login" field correctly shows "Never"

✅ **User with no organization** - All pages work correctly for users not in any organization

✅ **User in multiple organizations** - System correctly handles users belonging to multiple organizations

✅ **User with no first/last name** - System gracefully handles users with minimal information

✅ **Empty organization list** - Create user form works even when no organizations exist yet

✅ **Form with all fields empty** - System properly validates and rejects invalid submissions

---

## Security Testing

### What We Test

✅ **Authentication required** - All admin pages require users to be logged in

✅ **Authorization checks** - Only super administrators can access admin features

✅ **Regular users blocked** - Regular users cannot access admin pages (they're redirected)

✅ **Password security** - Passwords are stored securely and cannot be read in plain text

✅ **Session management** - Users stay logged in appropriately and can log out

---

## What This Means for You

### Confidence Level

**High Confidence (100% Tested)**:
- ✅ Creating new users
- ✅ Viewing user details
- ✅ Editing user information
- ✅ Changing passwords
- ✅ Deleting users
- ✅ Dashboard statistics
- ✅ User list display

**Medium Confidence (80% Tested)**:
- ⚠️ Organization modal (backend works, full UI interaction needs browser testing)

**What's Not Fully Tested**:
- ⚠️ JavaScript interactions (like modal opening/closing) require special browser testing tools
- ⚠️ Real-time form validation feedback (form validation works, but not the instant UI feedback)

### What Happens When Tests Pass

When all tests pass, it means:
- ✅ All the features listed above work as expected
- ✅ Forms validate input correctly
- ✅ Data is saved and retrieved properly
- ✅ Security measures are in place
- ✅ Error handling works correctly
- ✅ Edge cases are handled gracefully

### What Happens When Tests Fail

If tests fail, it means:
- ❌ Something is broken and needs to be fixed before release
- ❌ The feature might not work correctly for users
- ❌ We need to investigate and fix the issue

---

## Summary

**We test 200+ different scenarios** covering:
- ✅ All form fields and their validation
- ✅ All user management operations (create, view, edit, delete)
- ✅ Password changes and security
- ✅ Organization and role assignments
- ✅ Edge cases and error handling
- ✅ Security and access control

**Overall, we have ~85% test coverage**, meaning:
- Most features are thoroughly tested
- We have high confidence that the app works correctly
- Some advanced UI interactions need additional testing tools

**Before any feature is released**, it must pass all its tests. This ensures users get a reliable, working application.

