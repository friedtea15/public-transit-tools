############################################################################
## Tool name: BetterBusBuffers
## Created by: Melinda Morang, Esri, mmorang@esri.com
## Last updated: 6 December 2017
############################################################################
''' BetterBusBuffers - Count Trips at Points

BetterBusBuffers provides a quantitative measure of access to public transit
in your city by counting the transit trip frequency at various locations.

The Count Trips at Points tool takes a set of input points, finds the transit stops
reachable within a user-selected buffer distance, and counts the number of
transit trips that pass those stops during the time window selected. The tool
also calculates the number of trips per hour, the maximum time between
subsequent trips, and the number of stops within range of the input point.
'''
################################################################################
'''Copyright 2017 Esri
   Licensed under the Apache License, Version 2.0 (the "License");
   you may not use this file except in compliance with the License.
   You may obtain a copy of the License at
       http://www.apache.org/licenses/LICENSE-2.0
   Unless required by applicable law or agreed to in writing, software
   distributed under the License is distributed on an "AS IS" BASIS,
   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
   See the License for the specific language governing permissions and
   limitations under the License.'''
################################################################################

import os
import arcpy
import BBB_SharedFunctions


def runTool(outFile, SQLDbase, inPointsLayer, inLocUniqueID, day, start_time, end_time,
            inNetworkDataset, imp, BufferSize, restrictions, DepOrArrChoice):
    try:
        # Source FC names are not prepended to field names.
        arcpy.env.qualifiedFieldNames = False
        # It's okay to overwrite in-memory stuff.
        OverwriteOutput = arcpy.env.overwriteOutput # Get the orignal value so we can reset it.
        arcpy.env.overwriteOutput = True

        BBB_SharedFunctions.CheckArcVersion(min_version_pro="1.2")
        ProductName = BBB_SharedFunctions.ProductName
        BBB_SharedFunctions.CheckWorkspace()
        BBB_SharedFunctions.CheckOutNALicense()

        BBB_SharedFunctions.ConnectToSQLDatabase(SQLDbase)

        Specific, day = BBB_SharedFunctions.CheckSpecificDate(day)
        start_sec, end_sec = BBB_SharedFunctions.ConvertTimeWindowToSeconds(start_time, end_time)

        # Will we calculate the max wait time?
        CalcWaitTime = True

        impedanceAttribute = BBB_SharedFunctions.CleanUpImpedance(imp)

        # Hard-wired OD variables
        ExcludeRestricted = "EXCLUDE"
        PathShape = "NO_LINES"
        accumulate = ""
        uturns = "ALLOW_UTURNS"
        hierarchy = "NO_HIERARCHY"

        # Output file designated by user
        outDir = os.path.dirname(outFile)
        outFilename = os.path.basename(outFile)

        inLocUniqueID = BBB_SharedFunctions.HandleOIDUniqueID(inPointsLayer, inLocUniqueID)
        inLocUniqueID_qualified = inLocUniqueID + "_Input"

        arcpy.AddMessage("Run set up successfully.")

        # ----- Create a feature class of stops ------
        try:
            arcpy.AddMessage("Getting GTFS stops...")
            tempstopsname = "Temp_Stops"
            if ".shp" in outFilename:
                tempstopsname += ".shp"
            StopsLayer, StopList = BBB_SharedFunctions.MakeStopsFeatureClass(os.path.join(outDir, tempstopsname))
        except:
            arcpy.AddError("Error creating feature class of GTFS stops.")
            raise


        #----- Create OD Matrix between stops and user's points -----
        try:
            arcpy.AddMessage("Creating OD matrix between points and stops...")
            arcpy.AddMessage("(This step could take a while for large datasets or buffer sizes.)")

            # Name to refer to OD matrix layer
            outNALayer_OD = "ODMatrix"

            # ODLayer is the NA Layer object returned by getOutput(0)
            ODLayer = arcpy.na.MakeODCostMatrixLayer(inNetworkDataset, outNALayer_OD,
                                            impedanceAttribute, BufferSize, "",
                                            accumulate, uturns, restrictions,
                                            hierarchy, "", PathShape).getOutput(0)

            # To refer to the OD sublayers, get the sublayer names.  This is essential for localization.
            naSubLayerNames = arcpy.na.GetNAClassNames(ODLayer)
            points = naSubLayerNames["Origins"]
            stops = naSubLayerNames["Destinations"]

            # Add a field for stop_id as a unique identifier for stops.
            arcpy.na.AddFieldToAnalysisLayer(outNALayer_OD, stops,
                                            "stop_id", "TEXT")
            # Specify the field mappings for the stop_id field.
            fieldMappingStops = arcpy.na.NAClassFieldMappings(ODLayer, stops)
            fieldMappingStops["Name"].mappedFieldName = "stop_id"
            fieldMappingStops["stop_id"].mappedFieldName = "stop_id"
            # Add the GTFS stops as locations for the analysis.
            arcpy.na.AddLocations(outNALayer_OD, stops, StopsLayer,
                                    fieldMappingStops, "500 meters", "", "", "", "", "", "",
                                    ExcludeRestricted)
            # Clear out the memory because we don't need this anymore.
            arcpy.management.Delete(StopsLayer)

            # Add a field for unique identifier for points.
            arcpy.na.AddFieldToAnalysisLayer(outNALayer_OD, points,
                                            inLocUniqueID_qualified, "TEXT")
            # Specify the field mappings for the unique id field.
            fieldMappingPoints = arcpy.na.NAClassFieldMappings(ODLayer, points)
            fieldMappingPoints["Name"].mappedFieldName = inLocUniqueID
            fieldMappingPoints[inLocUniqueID_qualified].mappedFieldName = inLocUniqueID
            # Add the input points as locations for the analysis.
            arcpy.na.AddLocations(outNALayer_OD, points, inPointsLayer,
                                    fieldMappingPoints, "500 meters", "", "", "", "", "", "",
                                    ExcludeRestricted)

            # Solve the OD matrix.
            try:
                arcpy.na.Solve(outNALayer_OD)
            except:
                errs = arcpy.GetMessages(2)
                if "No solution found" in errs:
                    impunits = imp.split(" (Units: ")[1].split(")")[0]
                    arcpy.AddError("No transit stops were found within a %s %s walk of any of your input points.  \
Consequently, there is no transit service available to your input points, so no output will be generated." % (str(BufferSize), impunits))
                else:
                    arcpy.AddError("Failed to calculate travel time or distance between transit stops and input points.  OD Cost Matrix error messages:")
                    arcpy.AddError(errs)
                raise BBB_SharedFunctions.CustomError

            # Make layer objects for each sublayer we care about.
            if ProductName == 'ArcGISPro':
                naSubLayerNames = arcpy.na.GetNAClassNames(ODLayer)
                subLayerDict = dict((lyr.name, lyr) for lyr in ODLayer.listLayers())
                subLayers = {}
                for subL in naSubLayerNames:
                    subLayers[subL] = subLayerDict[naSubLayerNames[subL]]
            else:
                subLayers = dict((lyr.datasetName, lyr) for lyr in arcpy.mapping.ListLayers(ODLayer)[1:])
            linesSubLayer = subLayers["ODLines"]
            pointsSubLayer = subLayers["Origins"]
            stopsSubLayer = subLayers["Destinations"]

            # Get the OID fields, just to be thorough
            desc1 = arcpy.Describe(pointsSubLayer)
            points_OID = desc1.OIDFieldName
            desc2 = arcpy.Describe(stopsSubLayer)
            stops_OID = desc2.OIDFieldName

            # Join polygons layer with input facilities to port over the stop_id
            arcpy.management.JoinField(linesSubLayer, "OriginID", pointsSubLayer,
                                        points_OID, [inLocUniqueID_qualified])
            arcpy.management.JoinField(linesSubLayer, "DestinationID", stopsSubLayer,
                                        stops_OID, ["stop_id"])

            # Use searchcursor on lines to find the stops that are reachable from points.
            global PointsAndStops
            # PointsAndStops = {LocID: [stop_1, stop_2, ...]}
            PointsAndStops = {}
            ODCursor = arcpy.da.SearchCursor(linesSubLayer, [inLocUniqueID_qualified, "stop_id"])
            for row in ODCursor:
                PointsAndStops.setdefault(str(row[0]), []).append(str(row[1]))
            del ODCursor

        except:
            arcpy.AddError("Error creating OD matrix between stops and input points.")
            raise


        #----- Query the GTFS data to count the trips at each stop -----
        try:
            arcpy.AddMessage("Calculating the number of transit trips available during the time window...")

            # Get a dictionary of stop times in our time window {stop_id: [[trip_id, stop_time]]}
            stoptimedict = BBB_SharedFunctions.CountTripsAtStops(day, start_sec, end_sec, BBB_SharedFunctions.CleanUpDepOrArr(DepOrArrChoice), Specific)

        except:
            arcpy.AddError("Error calculating the number of transit trips available during the time window.")
            raise


        # ----- Generate output data -----
        try:
            arcpy.AddMessage("Writing output data...")

            arcpy.management.CopyFeatures(inPointsLayer, outFile)
            # Add a field to the output file for number of trips and num trips / hour.
            if ".shp" in outFilename:
                arcpy.management.AddField(outFile, "NumTrips", "SHORT")
                arcpy.management.AddField(outFile, "TripsPerHr", "DOUBLE")
                arcpy.management.AddField(outFile, "NumStops", "SHORT")
                arcpy.management.AddField(outFile, "MaxWaitTm", "SHORT")
            else:
                arcpy.management.AddField(outFile, "NumTrips", "SHORT")
                arcpy.management.AddField(outFile, "NumTripsPerHr", "DOUBLE")
                arcpy.management.AddField(outFile, "NumStopsInRange", "SHORT")
                arcpy.management.AddField(outFile, "MaxWaitTime", "SHORT")

            if ".shp" in outFilename:
                ucursor = arcpy.da.UpdateCursor(outFile,
                                                [inLocUniqueID[0:10], "NumTrips",
                                                "TripsPerHr", "NumStops",
                                                "MaxWaitTm"])
            else:
                ucursor = arcpy.da.UpdateCursor(outFile,
                                            [inLocUniqueID, "NumTrips",
                                            "NumTripsPerHr", "NumStopsInRange",
                                            "MaxWaitTime"])
            for row in ucursor:
                try:
                    ImportantStops = PointsAndStops[str(row[0])]
                except KeyError:
                    # This point had no stops in range
                    ImportantStops = []
                NumTrips, NumTripsPerHr, NumStopsInRange, MaxWaitTime =\
                                BBB_SharedFunctions.RetrieveStatsForSetOfStops(
                                    ImportantStops, stoptimedict, CalcWaitTime,
                                    start_sec, end_sec)
                row[1] = NumTrips
                row[2] = NumTripsPerHr
                row[3] = NumStopsInRange
                if ".shp" in outFilename and MaxWaitTime == None:
                    row[4] = -1
                else:
                    row[4] = MaxWaitTime
                ucursor.updateRow(row)

        except:
            arcpy.AddError("Error writing output.")
            raise

        arcpy.AddMessage("Done!")
        arcpy.AddMessage("Output files written:")
        arcpy.AddMessage("- " + outFile)

    except BBB_SharedFunctions.CustomError:
        arcpy.AddError("Error counting transit trips at input locations.")
        pass

    except:
        arcpy.AddError("Error counting transit trips at input locations.")
        raise

    finally:
        # Reset overwriteOutput to what it was originally.
        arcpy.env.overwriteOutput = OverwriteOutput