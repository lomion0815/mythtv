#include <unistd.h>

#include <QFileInfo>
#include <QFile>
#include <QDir>

#include "compat.h"
#include "remoteutil.h"
#include "programinfo.h"
#include "mythcorecontext.h"
#include "decodeencode.h"
#include "storagegroup.h"
#include "mythevent.h"

vector<ProgramInfo *> *RemoteGetRecordedList(int sort)
{
    QString str = "QUERY_RECORDINGS ";
    if (sort < 0)
        str += "Descending";
    else if (sort > 0)
        str += "Ascending";
    else
        str += "Unsorted";

    QStringList strlist(str);

    vector<ProgramInfo *> *info = new vector<ProgramInfo *>;

    if (!RemoteGetRecordingList(*info, strlist))
    {
        delete info;
        return NULL;
    }
 
    return info;
}

/** \fn RemoteGetFreeSpace(void)
 *  \brief Returns total and used space in kilobytes for each backend.
 */
vector<FileSystemInfo> RemoteGetFreeSpace(void)
{
    FileSystemInfo fsInfo;
    vector<FileSystemInfo> fsInfos;
    QStringList strlist(QString("QUERY_FREE_SPACE_LIST"));

    if (gCoreContext->SendReceiveStringList(strlist))
    {
        QStringList::const_iterator it = strlist.begin();
        while (it != strlist.end())
        {
            fsInfo.hostname = *(it++);
            fsInfo.directory = *(it++);
            fsInfo.isLocal = (*(it++)).toInt();
            fsInfo.fsID = (*(it++)).toInt();
            fsInfo.dirID = (*(it++)).toInt();
            fsInfo.blocksize = (*(it++)).toInt();
            fsInfo.totalSpaceKB = decodeLongLong(strlist, it);
            fsInfo.usedSpaceKB = decodeLongLong(strlist, it);
            fsInfos.push_back(fsInfo);
        }
    }

    return fsInfos;
}

bool RemoteGetLoad(float load[3])
{
    QStringList strlist(QString("QUERY_LOAD"));

    if (gCoreContext->SendReceiveStringList(strlist))
    {
        load[0] = strlist[0].toFloat();
        load[1] = strlist[1].toFloat();
        load[2] = strlist[2].toFloat();
        return true;
    }

    return false;
}

bool RemoteGetUptime(time_t &uptime)
{
    QStringList strlist(QString("QUERY_UPTIME"));

    if (!gCoreContext->SendReceiveStringList(strlist))
        return false;

    if (!strlist[0].at(0).isNumber())
        return false;

    if (sizeof(time_t) == sizeof(int))
        uptime = strlist[0].toUInt();
    else if (sizeof(time_t) == sizeof(long))
        uptime = strlist[0].toULong();
    else if (sizeof(time_t) == sizeof(long long))
        uptime = strlist[0].toULongLong();

    return true;
}

bool RemoteGetMemStats(int &totalMB, int &freeMB, int &totalVM, int &freeVM)
{
    QStringList strlist(QString("QUERY_MEMSTATS"));

    if (gCoreContext->SendReceiveStringList(strlist))
    {
        totalMB = strlist[0].toInt();
        freeMB  = strlist[1].toInt();
        totalVM = strlist[2].toInt();
        freeVM  = strlist[3].toInt();
        return true;
    }

    return false;
}

bool RemoteCheckFile(const ProgramInfo *pginfo, bool checkSlaves)
{
    QStringList strlist("QUERY_CHECKFILE");
    strlist << QString::number((int)checkSlaves);
    pginfo->ToStringList(strlist);

    if ((!gCoreContext->SendReceiveStringList(strlist)) ||
        (!strlist[0].toInt()))
        return false;

    // Only modify the pathname if the recording file is available locally on
    // this host
    QString localpath = strlist[1];
    QFile checkFile(localpath);
    if (checkFile.exists())
        pginfo->SetPathname(localpath);

    return true;
}

bool RemoteDeleteRecording(
    uint chanid, const QDateTime &recstartts, bool forceMetadataDelete,
    bool forgetHistory)
{
    bool result = true;
    QString cmd =
        QString("DELETE_RECORDING %1 %2 %3 %4")
        .arg(chanid)
        .arg(recstartts.toString(Qt::ISODate))
        .arg(forceMetadataDelete ? "FORCE" : "NO_FORCE")
        .arg(forgetHistory ? "FORGET" : "NO_FORGET");
    QStringList strlist(cmd);

    if (!gCoreContext->SendReceiveStringList(strlist) || strlist.empty())
        result = false;
    else if (strlist[0].toInt() == -2)
        result = false;

    if (!result)
    {
        VERBOSE(VB_IMPORTANT, QString("Failed to delete recording %1:%2")
                .arg(chanid).arg(recstartts.toString(Qt::ISODate)));
    }

    return result;
}

bool RemoteUndeleteRecording(uint chanid, const QDateTime &recstartts)
{
    bool result = false;

    bool undelete_possible = 
            gCoreContext->GetNumSetting("AutoExpireInsteadOfDelete", 0);

    if (!undelete_possible)
        return result;

    QStringList strlist(QString("UNDELETE_RECORDING"));
    strlist.push_back(QString::number(chanid));
    strlist.push_back(recstartts.toString(Qt::ISODate));

    gCoreContext->SendReceiveStringList(strlist);

    if (strlist[0].toInt() == 0)
        result = true;

    return result;
}

void RemoteGetAllScheduledRecordings(vector<ProgramInfo *> &scheduledlist)
{
    QStringList strList(QString("QUERY_GETALLSCHEDULED"));
    RemoteGetRecordingList(scheduledlist, strList);
}

void RemoteGetAllExpiringRecordings(vector<ProgramInfo *> &expiringlist)
{
    QStringList strList(QString("QUERY_GETEXPIRING"));
    RemoteGetRecordingList(expiringlist, strList);
}

uint RemoteGetRecordingList(
    vector<ProgramInfo *> &reclist, QStringList &strList)
{
    if (!gCoreContext->SendReceiveStringList(strList))
        return 0;

    int numrecordings = strList[0].toInt();
    if (numrecordings <= 0)
        return 0;

    if (numrecordings * NUMPROGRAMLINES + 1 > (int)strList.size())
    {
        VERBOSE(VB_IMPORTANT, "RemoteGetRecordingList() "
                "list size appears to be incorrect.");
        return 0;
    }

    uint reclist_initial_size = (uint) reclist.size();
    QStringList::const_iterator it = strList.begin() + 1;
    for (int i = 0; i < numrecordings; i++)
    {
        ProgramInfo *pginfo = new ProgramInfo(it, strList.end());
            reclist.push_back(pginfo);
    }

    return ((uint) reclist.size()) - reclist_initial_size;
}

vector<ProgramInfo *> *RemoteGetConflictList(const ProgramInfo *pginfo)
{
    QString cmd = QString("QUERY_GETCONFLICTING");
    QStringList strlist( cmd );
    pginfo->ToStringList(strlist);

    vector<ProgramInfo *> *retlist = new vector<ProgramInfo *>;

    RemoteGetRecordingList(*retlist, strlist);
    return retlist;
}

vector<uint> RemoteRequestFreeRecorderList(void)
{
    vector<uint> list;

    QStringList strlist("GET_FREE_RECORDER_LIST");

    if (!gCoreContext->SendReceiveStringList(strlist, true))
        return list;

    QStringList::const_iterator it = strlist.begin();
    for (; it != strlist.end(); ++it) 
        list.push_back((*it).toUInt());

    return list;
}

void RemoteSendMessage(const QString &message)
{
    if (gCoreContext->IsBackend())
    {
        gCoreContext->dispatch(MythEvent(message));
        return;
    }

    QStringList strlist( "MESSAGE" );
    strlist << message;

    gCoreContext->SendReceiveStringList(strlist);
}

void RemoteSendEvent(const MythEvent &event)
{
    if (gCoreContext->IsBackend())
    {
        gCoreContext->dispatch(event);
        return;
    }

    QStringList strlist( "MESSAGE" );
    strlist << event.Message();
    strlist << event.ExtraDataList();

    gCoreContext->SendReceiveStringList(strlist);
}

QDateTime RemoteGetPreviewLastModified(const ProgramInfo *pginfo)
{
    QDateTime retdatetime;

    QStringList strlist( "QUERY_PIXMAP_LASTMODIFIED" );
    pginfo->ToStringList(strlist);
    
    if (!gCoreContext->SendReceiveStringList(strlist))
        return retdatetime;

    if (!strlist.empty() && strlist[0] != "BAD")
    {
        uint timet = strlist[0].toUInt();
        retdatetime.setTime_t(timet);
    }
        
    return retdatetime;
}

/// Download preview & get timestamp if newer than cachefile's
/// last modified time, otherwise just get the timestamp
QDateTime RemoteGetPreviewIfModified(
    const ProgramInfo &pginfo, const QString &cachefile)
{
    QString loc_err("RemoteGetPreviewIfModified, Error: ");

    QDateTime cacheLastModified;
    QFileInfo cachefileinfo(cachefile);
    if (cachefileinfo.exists())
        cacheLastModified = cachefileinfo.lastModified();

    QStringList strlist("QUERY_PIXMAP_GET_IF_MODIFIED");
    strlist << ((cacheLastModified.isValid()) ? // unix secs, UTC
                QString::number(cacheLastModified.toTime_t()) : QString("-1"));
    strlist << QString::number(200 * 1024); // max size of preview file
    pginfo.ToStringList(strlist);

    if (!gCoreContext->SendReceiveStringList(strlist) ||
        strlist.empty() || strlist[0] == "ERROR")
    {
        VERBOSE(VB_IMPORTANT, loc_err +
                QString("Remote error") +
                ((strlist.size() >= 2) ?
                 (QString(":\n\t\t\t") + strlist[1]) : QString("")));

        return QDateTime();
    }

    if (strlist[0] == "WARNING")
    {
        VERBOSE(VB_NETWORK, QString("RemoteGetPreviewIfModified, Warning: ") +
                QString("Remote warning") +
                ((strlist.size() >= 2) ?
                 (QString(":\n\t\t\t") + strlist[1]) : QString("")));

        return QDateTime();
    }

    QDateTime retdatetime;
    qlonglong timet = strlist[0].toLongLong();
    if (timet >= 0)
        retdatetime.setTime_t(timet);

    if (strlist.size() < 4)
    {
        return retdatetime;
    }

    size_t  length     = strlist[1].toULongLong();
    quint16 checksum16 = strlist[2].toUInt();
    QByteArray data = QByteArray::fromBase64(strlist[3].toAscii());
    if ((size_t) data.size() < length)
    { // (note data.size() may be up to 3 bytes longer after decoding
        VERBOSE(VB_IMPORTANT, loc_err +
                QString("Preview size check failed %1 < %2")
                .arg(data.size()).arg(length));
        return QDateTime();
    }
    data.resize(length);

    if (checksum16 != qChecksum(data.constData(), data.size()))
    {
        VERBOSE(VB_IMPORTANT, loc_err + "Preview checksum failed");
        return QDateTime();
    }

    QString pdir(cachefile.section("/", 0, -2));
    QDir cfd(pdir);
    if (!cfd.exists() && !cfd.mkdir(pdir))
    {
        VERBOSE(VB_IMPORTANT, loc_err +
                QString("Unable to create remote cache directory '%1'")
                .arg(pdir));

        return QDateTime();
    }

    QFile file(cachefile);
    if (!file.open(QIODevice::WriteOnly|QIODevice::Truncate))
    {
        VERBOSE(VB_IMPORTANT, loc_err +
                QString("Unable to open cached "
                        "preview file for writing '%1'")
                .arg(cachefile));

        return QDateTime();
    }

    off_t offset = 0;
    size_t remaining = length;
    uint failure_cnt = 0;
    while ((remaining > 0) && (failure_cnt < 5))
    {
        ssize_t written = file.write(data.data() + offset, remaining);
        if (written < 0)
        {
            failure_cnt++;
            usleep(50000);
            continue;
        }

        failure_cnt  = 0;
        offset      += written;
        remaining   -= written;
    }

    if (remaining)
    {
        VERBOSE(VB_IMPORTANT, loc_err +
                QString("Failed to write cached preview file '%1'")
                .arg(cachefile));

        file.resize(0); // in case unlink fails..
        file.remove();  // closes fd
        return QDateTime();
    }

    file.close();

    return retdatetime;
}

bool RemoteFillProgramInfo(ProgramInfo &pginfo, const QString &playbackhost)
{
    QStringList strlist( "FILL_PROGRAM_INFO" );
    strlist << playbackhost;
    pginfo.ToStringList(strlist);

    if (gCoreContext->SendReceiveStringList(strlist))
    {
        ProgramInfo tmp(strlist);
        if (tmp.HasPathname() || tmp.GetChanID())
        {
            pginfo = tmp;
            return true;
        }
    }

    return false;
}

QStringList RemoteRecordings(void)
{
    QStringList strlist("QUERY_ISRECORDING");

    if (!gCoreContext->SendReceiveStringList(strlist, false, false))
    {
        QStringList empty;
        empty << "0" << "0";
        return empty;
    }

    return strlist;
}

int RemoteGetRecordingMask(void)
{
    int mask = 0;

    QString cmd = "QUERY_ISRECORDING";

    QStringList strlist( cmd );

    if (!gCoreContext->SendReceiveStringList(strlist))
        return mask;

    if (strlist.empty())
        return 0;

    int recCount = strlist[0].toInt();

    for (int i = 0, j = 0; j < recCount; i++)
    {
        cmd = QString("QUERY_RECORDER %1").arg(i + 1);

        strlist = QStringList( cmd );
        strlist << "IS_RECORDING";

        if (gCoreContext->SendReceiveStringList(strlist) && !strlist.empty())
        {
            if (strlist[0].toInt())
            {
                mask |= 1<<i;
                j++;       // count active recorder
            }
        }
        else
        {
            break;
        }
    }

    return mask;
}

int RemoteGetFreeRecorderCount(void)
{
    QStringList strlist( "GET_FREE_RECORDER_COUNT" );

    if (!gCoreContext->SendReceiveStringList(strlist, true))
        return 0;

    if (strlist.empty())
        return 0;

    if (strlist[0] == "UNKNOWN_COMMAND")
    {
        cerr << "Unknown command GET_FREE_RECORDER_COUNT, upgrade "
                "your backend version." << endl;
        return 0;
    }

    return strlist[0].toInt();
}

bool RemoteGetFileList(QString host, QString path, QStringList* list,
                       QString sgroup, bool fileNamesOnly)
{

    // Make sure the list is empty when we get started
    list->clear();

    if (sgroup.isEmpty())
        sgroup = "Videos";

    *list << "QUERY_SG_GETFILELIST";
    *list << host;
    *list << StorageGroup::GetGroupToUse(host, sgroup);
    *list << path;
    *list << QString::number(fileNamesOnly);

    bool ok = gCoreContext->SendReceiveStringList(*list);

// Should the SLAVE UNREACH test be here ?
    return ok;
}

/**
 * Get recorder for a programme.
 *
 * \return recordernum if pginfo recording in progress, else 0
 */
int RemoteCheckForRecording(const ProgramInfo *pginfo)
{
    QStringList strlist( QString("CHECK_RECORDING") );
    pginfo->ToStringList(strlist);

    if (gCoreContext->SendReceiveStringList(strlist) && !strlist.empty())
        return strlist[0].toInt();

    return 0;
}

/**
 * Get status of an individual programme (with pre-post roll?).
 *
 * \retval  0  Not Recording
 * \retval  1  Recording
 * \retval  2  Under-Record
 * \retval  3  Over-Record
 */
int RemoteGetRecordingStatus(
    const ProgramInfo *pginfo, int overrecsecs, int underrecsecs)
{
    QDateTime curtime = QDateTime::currentDateTime();

    int retval = 0;

    if (pginfo)
    {
        if (curtime >= pginfo->GetScheduledStartTime().addSecs(-underrecsecs) &&
            curtime < pginfo->GetScheduledEndTime().addSecs(overrecsecs))
        {
            if (curtime >= pginfo->GetScheduledStartTime() &&
                curtime < pginfo->GetScheduledEndTime())
                retval = 1;
            else if (curtime < pginfo->GetScheduledStartTime() && 
                     RemoteCheckForRecording(pginfo) > 0)
                retval = 2;
            else if (curtime > pginfo->GetScheduledEndTime() && 
                     RemoteCheckForRecording(pginfo) > 0)
                retval = 3;
        }
    }

    return retval;
}

/**
 * \brief return list of currently recording shows
 */
vector<ProgramInfo *> *RemoteGetCurrentlyRecordingList(void)
{
    QString str = "QUERY_RECORDINGS ";
    str += "Recording";
    QStringList strlist( str );

    vector<ProgramInfo *> *reclist = new vector<ProgramInfo *>;
    vector<ProgramInfo *> *info = new vector<ProgramInfo *>;
    if (!RemoteGetRecordingList(*info, strlist))
    {
        if (info)
            delete info;
        return reclist;
    }

    ProgramInfo *p = NULL;
    vector<ProgramInfo *>::iterator it = info->begin();
    // make sure whatever RemoteGetRecordingList() returned
    // only has rsRecording shows
    for ( ; it != info->end(); it++)
    {
        p = *it;
        if (p->GetRecordingStatus() == rsRecording ||
            (p->GetRecordingStatus() == rsRecorded &&
             p->GetRecordingGroup() == "LiveTV"))
        {
            reclist->push_back(new ProgramInfo(*p));
        }
    }
    
    while (!info->empty())
    {
        delete info->back();
        info->pop_back();
    }
    if (info)
        delete info;

    return reclist; 
}

/* vim: set expandtab tabstop=4 shiftwidth=4: */
